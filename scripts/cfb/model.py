"""One season-independent margin model for weekly, final, and LOO fits.

Importing this module does not import numerical libraries or run inference.
Team membership, game eligibility, and ranking policy belong outside the model.
"""

from dataclasses import asdict, dataclass
from functools import partial
import hashlib
import json
import math
from numbers import Integral


@dataclass(frozen=True)
class Specification:
    version: str = "margin-of-merit-v6-historical-home"
    historical_home: bool = True
    theta_sd: float = 14.0
    home_mean: float = 2.0
    home_sd: float = 2.5
    sigma_floor: float = 8.0
    eta_sigma_mean: float = math.log(6.0)
    eta_sigma_sd: float = 0.75
    eta_nu_mean: float = math.log(5.0)
    eta_nu_sd: float = 0.9

    def __post_init__(self):
        values = asdict(self)
        if not self.version or not all(math.isfinite(v) for k, v in values.items() if k != "version"):
            raise ValueError("Model parameters must be finite and versioned")
        if self.sigma_floor < 0 or min(self.theta_sd, self.home_sd, self.eta_sigma_sd, self.eta_nu_sd) <= 0:
            raise ValueError("Prior scales must be positive; the scale floor cannot be negative")

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


CANONICAL = Specification()
# Separate research comparisons, never selected implicitly by season/week.
UNFLOORED_SENSITIVITY = Specification(
    version="margin-of-merit-unfloored-sensitivity-v1",
    historical_home=False, sigma_floor=0.0, eta_sigma_mean=math.log(14.0), eta_sigma_sd=0.75,
)
ARCHIVED_PRIOR = Specification(
    version="margin-of-merit-archived-scale-prior-v1",
    historical_home=False, sigma_floor=0.0, eta_sigma_mean=math.log(14.0), eta_sigma_sd=0.5,
)


def margin_model(n_teams, home, away, venue, margin, specification=CANONICAL, host=None, home_prior=None):
    """Venue is 1 at the home team's venue, 0 for a neutral-site game.

    The caller supplies eligible games as of its declared cutoff and the entire
    season's FBS roster, including teams with no eligible games yet. There are
    deliberately no year, week, final-fit, or previous-rating branches here.
    """
    import jax.numpy as jnp
    import numpyro
    import numpyro.distributions as dist

    with numpyro.plate("teams", n_teams):
        theta = numpyro.sample("theta", dist.Normal(0.0, specification.theta_sd))
    if specification.historical_home:
        if home_prior is None or host is None:
            raise ValueError('Current model requires the exact historical home prior and host indices')
        mean, chol = home_prior
        z = numpyro.sample('home_z', dist.Normal(0., 1.).expand((len(mean),)).to_event(1))
        effects = numpyro.deterministic('home_effect', mean + chol @ z)
        home_adv = numpyro.deterministic('home_adv', effects[0])
        game_home = home_adv + jnp.where(host > 0, effects[host], 0.)
    else:
        # Explicit forensic prior comparisons only; production requires v6.
        home_adv = numpyro.sample("home_adv", dist.Normal(specification.home_mean, specification.home_sd))
        game_home = home_adv
    eta_sigma = numpyro.sample("eta_sigma", dist.Normal(specification.eta_sigma_mean, specification.eta_sigma_sd))
    eta_nu = numpyro.sample("eta_nu", dist.Normal(specification.eta_nu_mean, specification.eta_nu_sd))
    sigma = numpyro.deterministic("sigma", specification.sigma_floor + jnp.exp(eta_sigma))
    nu = numpyro.deterministic("nu", 2.0 + jnp.exp(eta_nu))
    mu = theta[home] - theta[away] + game_home * venue
    with numpyro.plate("games", len(home)):
        numpyro.sample("margin", dist.StudentT(nu, mu, sigma), obs=margin)


def fit(n_teams, home, away, venue, margin, *, specification=CANONICAL,
        seed=20261120, warmup=1000, draws=1000, host=None, home_prior=None):
    """Four sequential NUTS chains; no approximate-inference fallback."""
    import jax
    import jax.numpy as jnp
    from numpyro.infer import MCMC, NUTS

    if n_teams < 2 or warmup < 1 or draws < 4 or not len(home):
        raise ValueError("A fit needs teams, games, warmup, and at least four draws per chain")
    if not len(home) == len(away) == len(venue) == len(margin):
        raise ValueError("Game arrays must have matching lengths")
    for h, a, v, m in zip(home, away, venue, margin):
        if not (isinstance(h, Integral) and isinstance(a, Integral) and 0 <= h < n_teams and 0 <= a < n_teams and h != a):
            raise ValueError("Invalid team index in a game")
        if v not in (0, 1) or not math.isfinite(m):
            raise ValueError("Invalid venue or scoring margin")

    jax.config.update("jax_enable_x64", True)
    home_args = {}
    if specification.historical_home:
        import numpy as np
        if home_prior is None or host is None or len(host) != len(home):
            raise ValueError('Current model requires a historical home prior and one host index per game')
        mean, chol = np.asarray(home_prior['mean']), np.asarray(home_prior['chol'])
        if (mean.ndim != 1 or chol.shape != (len(mean), len(mean))
                or not np.isfinite(mean).all() or not np.isfinite(chol).all()
                or any(not isinstance(i, Integral) or not 0 <= i < len(mean) for i in host)):
            raise ValueError('Invalid historical home prior or host indices')
        home_args = {'host': jnp.asarray(host, dtype=jnp.int32),
                     'home_prior': (jnp.asarray(mean, dtype=jnp.float64), jnp.asarray(chol, dtype=jnp.float64))}

    sampler = MCMC(
        NUTS(partial(margin_model, specification=specification), target_accept_prob=0.9, max_tree_depth=10),
        num_warmup=warmup, num_samples=draws, num_chains=4,
        chain_method="sequential", progress_bar=False,
    )
    sampler.run(
        jax.random.PRNGKey(seed), n_teams,
        jnp.asarray(home, dtype=jnp.int32), jnp.asarray(away, dtype=jnp.int32),
        jnp.asarray(venue, dtype=jnp.float64), jnp.asarray(margin, dtype=jnp.float64),
        extra_fields=("potential_energy", "energy", "num_steps", "accept_prob"),
        **home_args,
    )
    return sampler
