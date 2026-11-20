---
example: false
published: true
date: 2026-11-20
tags:
  - Sports
  - Bayesian
  - Rankings
  - Fairness
  - College Football
comments: true
title: College Football Has a Rankings Problem. So I Built My Own.
cover: /assets/images/editor-77c20c5f-6ae6-4a9b-ab76-1eb6da83e862.jpg
description: The CFP committee has no transparency when it comes to college football rankings. They're basically selecting them off vibes. Introducing "Margin of Merit", a transparent Bayesian ranking system that evaluates what teams have actually earned through wins, losses, scoring margins, and strength of schedule. No preseason bias, no arbitrary committee decisions—just results, statistical inference, and an honest accounting of uncertainty.
---
*Introducing the CFB Margin of Merit Rankings: a transparent, Bayesian approach to evaluating what teams have actually earned on the field.*

You can find updated rankings [here](https://nateoconnell.com/blog/cfb/), and also browse historic rankings based on my model as well. 

I'm a big sports fan, and one of my favorite sports is College Football. Not football in general, but specifically College Football. The tradition, the pageantry, the unpredictability, the chaos. Every fall, college football fans end up in the same argument. Which teams deserve to be ranked the highest at the end of the season? This argument has evolved over the years. Before the BCS it was simply who deserved to be crowned the national champion. Then it was who deserves to play in the National Championship. Then it became who deserves to play in the 4-team College Football Playoff. Now it's the 12-team playoff, and there is already discussion of expanding it further. And there's been plenty of controversy over the years -- 2023 FSU, 2004 Auburn, 2003 USC, 2011 Oklahoma State -- just to name a few. Just last year we had 10–2 Notre Dame left out of the 12-team CFP. And I don't see this going away; the controversy just shifts. If the playoff eventually expands to 24 teams, the debate becomes who gets that 24th spot, while the arguments at the top turn to first-round byes and home-field advantage. 

We debate which conference is stronger, how much a loss should matter, and whether an undefeated team with a weak schedule is more deserving than a two-loss team that played several of the best teams in the country.

And since 2014, every November, the College Football Playoff selection committee emerges from its deliberations, releases its rankings, and attempts to explain its decisions. How?

![Describe the image](/assets/images/editor-deed2884-a328-420a-8ecb-afb17994129d.jpg)

This entire process is ridiculous. [Mike Leach (RIP)](https://www.youtube.com/watch?v=y_nuMEtwUW4) nailed the absurdity nearly a decade ago, and it's only gotten worse. [Josh Pate's](https://www.youtube.com/watch?v=EY24JN-3FWU) rant just yesterday (at the time of this posting, November 20, 2026) captures my frustration with the committee and its approach to rankings. The problem isn't necessarily that the committee selects the wrong teams. It's that **there is no consistent, reproducible way to determine how it arrives at its decisions.**

One week, strength of schedule is emphasized. Another week, head-to-head results are decisive. Then perhaps a team's quality wins become the determining factor. Margin of victory matters when it's convenient. And sometimes a team is apparently just *better*, regardless of what it has actually accomplished. The committee has "published" selection criteria. It considers strength of schedule, head-to-head results, common opponents, and other measures of performance. But there is no transparent rule describing how those considerations are combined. And they apply them wildly inconsistently. 

Instead, thirteen people deliberate, compare teams, and ultimately vote. I don't care how much "reasoning" they give, what statistics they use -- they're effectively picking playoff teams and seeds based off vibes, and then post-hoc cherry picking the stats that fit the narrative they want. 

And they're picking teams based on what they **think** will happen, not based on resume, which I find to be the antithesis of competition. Results matter. I don't care what you **think** will happen. I don't care who you'd bet on. I don't care that in a theoretical world, that you think Team A will beat Team B 90% of the time. If Team A has the same record as Team B, and Team B won their head-to-head matchup, that result needs to matter. You can't just dismiss it because a power rating favors Team A. I don't care if a player got injured and that changes your perspective on how you **think** the team will perform going forward. This is a team based sport. Results matter. 

Cue [Josh Pate again](https://www.youtube.com/watch?v=VbO-Ma6tMb), in reference to the possibility of FSU getting left out of the 2023 CFP because their QB Jordan Travis got injured: "I detest the concept of a committee of people gathering together and deciding they know for sure the value of a football player. And how he benefits your team and without him what your team is. I cant stand that. I really think its time to emphasize ahead of time... is the difference better Vegas and merit. Power ratings and merit... It doesn't matter what you think you know. It matters what's been earned on the field by a football team. You can sit there and tell me that injuries are a part of football (which is accurate)... one player goes down... I got 21 others starting any given Saturday. It's a team game. Don't tell me injury is part of the game and then completely change the way you define merit and the way you select your teams from your committee because 'football happened.'"

"Games are played on the field, not paper"

Then the committee did it anyway.  After then leaving out undefeated FSU from the CFP, Bill Hancock (executive director of the CFP at the time) said, "Most deserving is not anything in the committee's lexicon. They are to rank the best teams in order, and that's what they do. Just keep that word in mind, best teams."

They changed their criteria. Again. And for the first time in the decade of the CFP choosing teams, they now say its based on their perception of "best" and not most deserving. [Josh Pate](https://www.youtube.com/watch?v=pfacP3nxqVc) again, called them out on this inconsistency. Even [Pate] agreeing that if "best" is the criteria, then Alabama deserved in over FSU, he says directly, "The Florida State folks are mad because they changed the rules in the middle of the game. And I cannot disagree with them. I think that's exactly what happened... I think the committee was baking expectations into the rankings. They expected you to lose... And then a source from the playoff committee... 'It was gut wrenching... for me individually, I evaluated whether FSU could make it through and win a national championship with the team they had.'... Now I'm telling you... it's complete garbage. If that's the methodology that anyone, much less an entire committee, used to keep Florida State out is garbage." 

You know what. I think I'm pretty strongly in-line with Josh Pate here. He has my vote for CFB commissioner. 

Imagine if the NFL decided its playoff seeding this way. A team finishes 12–5, another finishes 11–6, and a committee decides that the second team simply looks better. Maybe it had a harder schedule. Maybe it won more convincingly. Maybe its quarterback got injured, but the committee thinks it would have won with him healthy. Maybe a loss in October counts less than one in December.

That is not how sports are supposed to work. Results matter. No other professional sport on earth selects and seeds teams for a playoff based on *what they think would happen*. They select them off merit, off results of the season. And right now, as I write this, we're having the same debates about the current season. **This is an unacceptable way to evaluate what teams have earned.**

## The problem is harder than it looks

Now, there's an obvious objection to everything I just said: college football isn't the NFL. The Football Bowl Subdivision (FBS) has more than 130 teams, and each team plays only about 12 regular-season games. Most of those games occur within conferences, leaving relatively few opportunities to compare teams across the country.

Think about what that means. An SEC team might play eight conference games and several non-conference opponents. A Big Ten team faces an almost entirely different set of opponents. A Group of Five team may go undefeated without ever playing either of them.

How do we determine whether one team's 11–1 record is better than another team's 10–2 record? We can't simply compare wins. A win over Georgia tells us something very different from a win over Kent State (sorry Kent State, I don't mean any offense). But we also can't simply compare strength of schedule. Losing to excellent teams doesn't necessarily mean you've accomplished more than someone who actually beat the opponents in front of them. And we can't resolve everything using head-to-head results, because most teams never play each other.

In a 138-team FBS, there are

$$
\binom{138}{2}=9{,}453
$$

possible pairwise matchups.

A typical regular season contains only a fraction of those games, and the schedule isn't remotely balanced. **There is no way to construct a perfectly objective ranking from such incomplete information.** Some inference is unavoidable. But here's my argument: **the necessity of inference doesn't justify abandoning consistency or transparency.**

We can use mathematics to evaluate the information that actually exists, quantify what we don't know, and establish clear rules for how that evidence determines a ranking. We don't need thirteen people in a room deciding which statistics matter this week.

## What are we actually trying to rank?

So before introducing the model, there's an important distinction: **the best team isn't necessarily the most deserving team.** See my above rant. Suppose Team A is exceptionally talented, but loses three close games against excellent opponents. Team B goes undefeated against a more modest schedule.

If they played tomorrow on a neutral field, Team A might be favored. That's a predictive question: *Who is more likely to win?* This is what Vegas answers. This is what power ratings are. It's an interesting question in it's own right. But that's not the same as asking which team has earned the higher ranking through its actual results.

The second question is what interests me. It's kind of ironic that so much of my methodological research focuses on prediction and quantifying uncertainty prospectively, because here I care only about what's happened in the past. There are already plenty of predictive power ratings. They attempt to determine how teams would perform in hypothetical matchups, often using offensive efficiency, defensive efficiency, player quality, recruiting, and dozens of other variables.

Those models have their place. But I don't think we need to estimate every team's passing offense, run-blocking ability, defensive coverage, and quarterback talent to evaluate its résumé. At some point, we're trying to explain every component of football when the most relevant evidence is sitting directly in front of us. **Who did you play? Did you win? And by how much?** That's the information I want to use. 

Why? Because winning and scores, I would argue, are the ultimate manifestation of team quality in aggregate. I do not think that breaking down all of these individual level metrics and trying to model a teams "strength" based on 20 derived latent variables can be done with enough precision to honestly discriminate between teams of similar quality. What differentiates two teams with similar schedules shouldn't be these noisy constructs, but results that actually happened. 

And importantly, that's *all* I want to use. No recruiting rankings, preseason polls, historical reputation, or assumptions about how good a team ought to be. Every season starts fresh.

## Introducing Margin of Merit

I've been developing a ranking system I'm calling the **Margin of Merit Rankings**.

The name has two meanings. First, scoring margins matter: beating a strong opponent by 28 points is different from beating a weak opponent by 28. Second, the rankings themselves have margins. We shouldn't merely say Team A is sixth and Team B is seventh. We should quantify how much evidence separates them and how uncertain that ordering is. And we can. 

The entire system is based on five principles:

1. Actual wins and losses are the foundation of merit.
2. Opponent quality is learned from the entire network of FBS game results.
3. Scoring margins provide additional information, with bounded credit for increasingly large victories.
4. Head-to-head and common-opponent results determine qualifying comparisons through explicit posterior-probability thresholds, while protected merit orderings cannot be overridden.
5. Rankings should communicate uncertainty rather than manufacture precision.

This is founded on fairness and transparency, and rankings are purely based on merit of what's happened on the field. The implementation uses a Bayesian model framework, but the underlying idea is fairly straightforward.

## Learning from the entire network of games

Imagine three teams: Team A beats Team B by 35 points. Team B loses its next four games by 25, 30, 28, and 35 points. That makes Team A's victory look considerably less impressive than it first appeared. Now imagine instead that Team B beats three strong opponents and narrowly loses to a fourth. Suddenly, Team A's 35-point victory looks extraordinary. The score against Team B hasn't changed. What changed is our understanding of how good Team B actually is. And that information doesn't stop at Team B's direct opponents. Their results against other teams also contribute to our understanding. This conceptually expands across a network of all 138 FBS teams in an interconnected web that no one could reasonably draw out.

**College football is a network of interconnected game outcomes.** The mathematical model needs to account for that network. I start with a scoring-margin version of a paired-comparison model, related in spirit to the Bradley–Terry framework. Rather than fitting only whether a team won or lost, I use the final scoring margin from every completed FBS-versus-FBS game. Why? Because a win by 3 is not the same as a win by 28.

### The Bayesian model: likelihood, priors, and posterior

Let $$\theta_i$$ represent the underlying strength of team $$i$$, measured in points. For game $$g$$, let $$h(g)$$ and $$a(g)$$ denote the designated home and away teams, and define the observed scoring margin as

$$
Y_g=\text{Home points}_g-\text{Away points}_g.
$$

For neutral-site games, we don't award either team a home-field advantage. With $$z_g=1$$ for a true home game and $$z_g=0$$ for a neutral site, the likelihood is

$$
\boxed{
Y_g\mid\boldsymbol\theta,h,\sigma,\nu
\sim t_\nu\!\left(\theta_{h(g)}-\theta_{a(g)}+z_gh,\ \sigma\right).
}
$$

The expected scoring margin is the difference in the teams' strengths, adjusted for home field. The parameter $$h$$ is home-field advantage in points; $$\sigma$$ describes ordinary game-to-game variation; and $$\nu$$ controls the heaviness of the tails. I use a Student's *t* distribution because football scores are noisy and sometimes extreme. A few strange blowouts shouldn't completely dictate estimates of team strength, but I also don't want to throw away the information contained in actual scoring margins.

A Bayesian model also requires prior distributions. Here is the actual specification used in the 2026 implementation:

$$
\begin{aligned}
\theta_i &\overset{\mathrm{iid}}{\sim} N(0,14^2),\\
h &\sim N(2,2.5^2),\\
\eta_\sigma &\sim N(\log 6,0.75^2),
&\sigma &=8+e^{\eta_\sigma},\\
\eta_\nu &\sim N(\log 5,0.9^2),
&\nu &=2+e^{\eta_\nu}.
\end{aligned}
$$

Those numbers are modeling choices, and I'm publishing them rather than hiding them. Every team starts with **exactly the same prior**, centered at zero with a 14-point prior standard deviation. No teams get a higher prior because of recruiting, conference affiliation, history, or a preseason ranking. The home-field prior is centered at two points. The eight-point lower bound is on the Student's *t* **scale**, not the standard deviation of team strength; it's a conservative regularization choice that prevents the model from estimating implausibly little game-to-game variation when only a handful of results exist early in the season. The same specification is used throughout the season.

With $$D=\{Y_1,\ldots,Y_G\}$$ denoting all completed FBS game margins and $$\Theta=(\boldsymbol\theta,h,\sigma,\nu)$$, Bayes' rule gives

$$
\boxed{
p(\Theta\mid D)
\propto
p(\Theta)\prod_{g=1}^{G}
t_\nu\!\left(Y_g\mid\theta_{h(g)}-\theta_{a(g)}+z_gh,\sigma\right).
}
$$

In plain English, the posterior combines the same starting assumptions for every team with the likelihood of all the scores we actually observed. I fit this joint posterior using Hamiltonian Monte Carlo, with four independent chains. Rather than getting a single strength number for Georgia or Texas, I get thousands of draws representing plausible combinations of **all** team strengths, home-field advantage, and game variability. As additional games are played, the posterior updates, and the network supplies more information about the relative quality of teams that may never face each other.

This is why strength of schedule emerges from the results rather than from arbitrary conference weights. Nothing in the prior says the SEC or Big Ten should be stronger than anyone else. If a conference consistently performs better against outside opponents, that evidence propagates through the network. And because the model is Bayesian, the uncertainty in comparisons between weakly connected teams remains visible.

But there's another important distinction: **these underlying strength estimates are not the merit rankings.** They tell us how difficult a particular outcome was. To rank what teams have *earned*, I construct a separate measure from the games they actually played.

## How much is a particular victory worth?

Here's where the model gets interesting. Suppose Ohio State beats Alabama by 17 points. How impressive is that? One way to answer is to imagine a fixed reference-quality team—say, a team with approximately top-25 FBS strength—facing Alabama at the same venue. Based on the fitted model, what scoring margin would we expect that reference team to achieve? We can calculate an entire probability distribution of possible margins, then ask where Ohio State's actual 17-point victory falls within it.

The reference team isn't a particular school. In each posterior draw, I use the **25th-highest latent team strength** as the benchmark. This means the reference itself is allowed to be uncertain, rather than pretending we know exactly how good the 25th-best team is. For a result by team $$i$$ against opponent $$j$$, let $$m_{ig}$$ be the actual margin from team $$i$$'s perspective, and let $$v_{ig}$$ be $$+1$$ at home, $$0$$ on a neutral field, and $$-1$$ away. The reference team's scoring-margin distribution has cumulative distribution function

$$
\boxed{
F_{ig}(m\mid\Theta)=
T_\nu\!\left(
\frac{m-(\theta_{\mathrm{ref}}-\theta_j+v_{ig}h)}{\sigma}
\right),
}
$$

where $$T_\nu$$ is the cumulative distribution function of the Student's *t* distribution and $$\theta_{\mathrm{ref}}$$ is the 25th-highest $$\theta$$ in the particular posterior draw. In ordinary terms, $$F_{ig}(m)$$ tells us how often a top-25-caliber team would be expected to produce a margin **no greater than** $$m$$ against that specific opponent in that venue.

If very few plausible outcomes are as impressive as a 17-point victory, Ohio State has accomplished something substantial. If a typical top-25 team would be expected to beat that opponent by 25 points, the same 17-point win deserves less credit. We turn that comparison into a game-level measure of merit:

$$
\boxed{
c_{ig}=F_{ig}(m_{ig})-\mathbb{1}(m_{ig}<0).
}
$$

The indicator term equals 1 when the observed result is a loss and 0 otherwise. **Every win receives positive merit**, between 0 and 1, and **every loss receives negative merit**, between −1 and 0. A larger victory earns more credit than a smaller victory against the same opponent. Beating a strong opponent by 20 earns more than beating a weak opponent by 20; losing narrowly to an excellent opponent is penalized less than losing badly to a weak opponent. Because the scoring function is bounded, no team can accumulate unlimited merit by running up the score. A 40-point victory can earn more than a 22-point victory, without declaring the two results identical or creating arbitrary blowout categories.

For each posterior draw $$s$$, I compute each game's credit using its corresponding posterior opponent and reference strengths, and sum the credits over the actual FBS schedule $$G_i$$:

$$
\boxed{
\mathcal M_i^{(s)}=\sum_{g\in G_i}c_{ig}^{(s)}.
}
$$

This gives every team a **posterior distribution of earned merit**, not merely a point estimate. Its posterior mean is the foundation of the ranking, and its distribution lets me compare teams probabilistically. One important qualification: bounded credit doesn't eliminate every incentive to run up a score. It does ensure that credit has an upper limit and that extremely large margins eventually add very little.

## An important statistical safeguard: Leave the game out

There's a subtle problem in evaluating an opponent's strength using the same game we're trying to score. Suppose Team A beats Team B by 40 points. That blowout is evidence that Team A is strong, but also evidence that Team B is weak. If we use that same game to make Team B look weaker and then evaluate how impressive Team A's victory was against the newly weakened opponent, we've created a feedback problem: the victory can discount itself.

Instead, I use **leave-one-game-out inference**. When evaluating a particular game, the opponent-quality comparison is based on the rest of the season's results, with that game omitted. If $$D_{-g}$$ denotes all the observed margins except game $$g$$, the relevant posterior is

$$
\boxed{
p(\Theta\mid D_{-g})
\propto\frac{p(\Theta\mid D)}{p(Y_g\mid\Theta)}.
}
$$

This relationship also gives a computational shortcut. Rather than refitting the entire Bayesian model hundreds of times, I use Pareto-smoothed importance sampling to approximate each game's leave-one-out posterior, with weights proportional to the **inverse** probability density of that game's observed score. I monitor the Pareto diagnostics and can refit individual games when the approximation becomes unreliable.

The per-game merit credit is therefore actually

$$
\boxed{
c_{ig}^{(s,-g)}
=F_{ig}^{(s,-g)}(m_{ig})-\mathbb{1}(m_{ig}<0),
\qquad
\mathcal M_i^{(s)}=\sum_{g\in G_i}c_{ig}^{(s,-g)}.
}
$$

This allows the opponent's other results—and the interconnected schedule network—to determine the value of the result without letting that same result directly discount itself. To combine game-specific leave-one-out calculations into season-level merit distributions, the current implementation uses an approximation to their joint dependence. The uncertainty I report is therefore estimated, not an exact probability law for every imaginable ranking.

## Strength of schedule, without conference reputation

The model also gives us a natural strength-of-schedule measure. For every opponent on a team's schedule, we estimate the probability that our reference-quality team would lose that matchup, accounting for venue. We then average those probabilities across the schedule:

$$
\boxed{
\operatorname{SOS}_i
=
\frac{1}{n_i}
\sum_{g\in G_i}
P(\text{reference loses game }g\mid D_{-g}).
}
$$

This produces a strength-of-schedule measure between 0 and 1. An SOS of 0.45 means our reference team would be expected to lose approximately 45% of those games. That's considerably more interpretable than saying someone has the 37th-hardest schedule according to a formula nobody can inspect. 

And we can quantify the uncertainty. For example, we can estimate the probability that Georgia's schedule was genuinely more difficult than Oregon's, rather than pretending their estimated SOS ranks are exact. The entire measure comes from current-season game results. We don't assume the SEC or Big Ten is stronger because of reputation. If one conference is genuinely stronger, that should emerge from its results against the rest of the network.

## But actual results should still matter most

I don't want to create another computer ranking that ignores the obvious evidence of what happened on the field. Suppose two teams both finish 10–2, and one defeated the other. I think that head-to-head result should matter. But that doesn't mean it should **automatically** put the winner ahead regardless of everything else either. A single game is part of a season, not the entire season. And I certainly don't want a head-to-head result between teams ranked 12th and 24th to make the algorithm simply swap those teams, dragging unrelated teams along with them.

This is where the uncertainty in merit becomes useful. Because I have a posterior distribution of merit for every team, I can calculate the probability that one has actually earned more than another. For teams $$i$$ and $$j$$, define

$$
\boxed{
p_{ij}=P(\mathcal M_i>\mathcal M_j\mid D).
}
$$

Suppose Team A has higher *average* merit than Team B, but B beat A head-to-head. If $$p_{AB}=0.85$$, the model gives A an 85% probability of having earned more merit despite losing that game. How should those two pieces of evidence be reconciled? My solution is to make the decision rule explicit, and to let readers change it themselves. There are three independently adjustable probability thresholds, each of which answers a specific question. They aren't weights added to a score. **Every percentage determines whether a particular ranking rule applies.**

The first is the **head-to-head threshold**, which I'm initially setting at **90%**. Its meaning is literal: *if B beat A, put B ahead of A unless the model gives A more than a 90% probability of having earned greater merit*. If that probability is 85%, head-to-head determines their comparison. If it is 91%, it doesn't. Lowering the threshold to 70% means a head-to-head result can reverse the merit ordering only when the evidence favoring the loser is 70% or less. Raising it to 95% allows head-to-head to resolve comparisons that the model distinguishes more confidently. This isn't a 90% bonus, or a subjective number of points awarded for winning a particular game. It is a precise yes-or-no rule.

The second is the **common-opponent threshold**, initially **70%**. **This rule is used only when two teams have not played each other at all.** If they played, head-to-head has priority, even if they split their games or the head-to-head result wasn't strong enough to change the ranking. We do not go hunting through common opponents for another reason to move them. When two teams never met, I compare their win–loss results against opponents they both played. A team has an unambiguous advantage only if it did at least as well against *every* common opponent and strictly better against at least one. If B has that advantage, put B ahead of A unless the probability that A has higher merit is greater than 70%. At 69%, the common-opponent result determines that comparison; at 71%, it doesn't, unless another higher-priority requirement applies. Scoring margins against those opponents already contribute to the underlying merit estimates; this particular rule concerns actual wins and losses.

The third is **merit protection**, initially **90%**. It says: *if the posterior gives A more than a 90% probability of having higher merit than B, A must stay ahead of B, regardless of the head-to-head or common-opponent rule.* Unlike the other two thresholds, this applies to **every pair of FBS teams**, not only teams that played one another. This makes its role different from the head-to-head threshold: head-to-head tells us when a direct result creates an ordering requirement; merit protection tells us which pairwise orderings cannot be overturned. The sliders are independent. If head-to-head is set to 95% but merit protection to 90%, a comparison supported by 92% merit probability remains protected even though it passes the head-to-head test. I want readers to be able to change all three thresholds, rather than hide those decisions inside the algorithm.

Importantly, I am **not** using distance in the numbered rankings to define whether teams are close. Not within two positions, three positions, or any fixed number. Proximity means *statistical uncertainty in their merit*. Teams twelve positions apart can have sufficiently overlapping merit posteriors for a head-to-head result to qualify; two adjacent teams can have such strong merit evidence separating them that their order is protected. The specific posterior probability—not their position on a list—determines whether the rule applies. The ranking algorithm likewise does not use rank-position distance to resolve conflicts between eligible results.

For now, the default is to apply the head-to-head and common-opponent rules only to teams with **identical FBS win–loss records**. That, too, will be a visible on/off setting; turning it off permits the same probability-based comparisons across different records. The actual Bayesian merit scores, posterior probabilities, and strength-of-schedule estimates do not change when someone adjusts these settings. Only the rules for constructing the final published order change.

But what about the teams in between? Suppose the original merit order is **A #10, X #11, B #12**, and B beat A. If the posterior gives A only a 65% probability of greater merit than B, the 90% head-to-head threshold says B should go ahead of A. That **does not** mean I exchange their numerical ranking positions. The algorithm must also respect every protected comparison involving X. If no higher-priority ordering blocks the change, the adjusted order could be **X, B, A**: B passes A without being artificially promoted above X. But suppose the evidence strongly protects **A ahead of X** and **X ahead of B**. Those requirements imply A must stay above B, so B's otherwise eligible head-to-head result cannot be enforced. The system reports that conflict and the specific chain of comparisons preventing the move. It doesn't quietly trade off the conflicting evidence using arbitrary numerical penalties.

Mathematically, the procedure starts with the ranking $$\pi_0$$ obtained by sorting teams by posterior **mean merit**. It then constructs pairwise ordering requirements. First come the protected merit comparisons, followed by qualifying head-to-head results. Common-opponent comparisons are considered **only for pairs that never played each other**. No rank-gap cutoff enters this process. A requirement is accepted if it is compatible with the requirements already established. If two requirements cannot both hold—for example, because they create a cycle—the later, lower-priority requirement is rejected and the conflicting chain is recorded. When multiple head-to-head requirements conflict, the algorithm first considers the one most consistent with the posterior merit evidence, with published deterministic tie-breaks for remaining ties. There are no additional head-to-head bonus points, movement penalties, or tuning coefficients.

Once those comparisons are established, the algorithm produces the final numbered ranking using a **stable topological ordering**: at each position, it selects the highest-ranked team by mean merit among those not required to sit below another team. This respects every accepted comparison without hot-swapping two teams or rearranging an entire group just because they have the same record. It is deterministic and auditable, although it does not claim to find the one ordering that minimizes every possible measure of movement from the original list. The important point is that every change can be traced to a particular probability threshold, an actual game result, or an explicitly documented conflict-resolution rule.

There is also one separate, explicit fairness rule: an undefeated Power Four team with at least eight completed FBS games stays ahead of teams with two or more FBS losses. That is a stated protection for an undefeated résumé, not something I claim the likelihood mathematically proves, and readers will be able to turn it on or off. **Merit establishes the baseline; actual head-to-head and common-opponent results determine specific comparisons when the published thresholds say they should.** Where the rules conflict, the conflict is visible rather than concealed inside a set of arbitrary weights.

## Rankings should have margins of error

Maybe the most important thing I think people overlook is uncertainty. Traditional college football rankings give us a numbered list, without distinguishing how confident we should be in any particular ordering. Team A is sixth, Team B is seventh, Team C is eighth. But how different are they, really? A ranking creates the impression of a precise ordering even when the evidence may barely distinguish adjacent teams.

In the Bayesian framework, every team has a posterior distribution of merit. We can calculate $$P(\mathcal M_A>\mathcal M_B\mid D)$$, the probability that Team A has earned more merit than Team B, based on the observed season and the model. We can also report each team's probability of landing in the top 10 or top 25 **by merit**, along with a credible range of plausible merit ranks. A team might be ranked seventh but have a plausible rank range from fourth to fifteenth. Another might be eighth with a much narrower range. Those are very different situations, and a ranking should communicate that difference.

Because the official ordering can also reflect these explicit head-to-head, common-opponent, and undefeated-team rules, I distinguish **posterior merit probabilities** from the final, policy-adjusted integer ranking. The current implementation approximates the joint dependence of the leave-one-game-out merit calculations, so those probabilities should not be mistaken for exact facts. Still, the principle is simple: **we should distinguish what the evidence suggests from how confidently it supports that conclusion.**

## Why I won't publish rankings in Week 1

Early-season rankings are another aspect of college football that I find difficult to justify. After one or two games, we have very little current-season evidence about most teams. Many haven't even played an FBS opponent. A statistically honest ranking should reflect that. My model doesn't use preseason rankings, the AP or Coaches Poll, or advanced performance metrics. It uses completed FBS game scores and venues. That's it. 

The Bayesian model begins every season with the same prior assumptions for every FBS team. It does not carry forward last season's team ratings, recruiting expectations, or preseason polls. As games are played, the network becomes more connected and the posterior distributions begin to separate. I tested this process by reconstructing the 2024 season week by week, using only the results available at each point. Early in the season, there was enormous uncertainty in the relative rankings. After Week 1, many teams were essentially indistinguishable based on the evidence. By Week 4, the schedule network was connected, but substantial uncertainty remained. In the 2024 reconstruction, the first reasonable point for publishing numbered rankings was **Week 6**.

So that's how I intend to present the system. Early in the season, I'll publish a **Margin Monitor**, showing emerging evidence, broad groups of teams, posterior probabilities, and uncertainty without pretending there is a meaningful ranking from 1 through 25.

Once enough results accumulate, I'll begin publishing the **Margin of Merit Top 25**. And if a particular season takes longer to produce informative rankings, that's fine. The data should determine when the evidence is sufficient—not an arbitrary publication schedule.

## Is this the perfect ranking?

Of course not. There is no uniquely correct mathematical definition of which college football team is the most deserving. With 138 teams playing roughly 12 games each, with games clustered within conferences, we have to make choices. How strongly should we prioritize head-to-head results? What constitutes a fair comparison of unequal schedules? Which reference team should define the benchmark? How should undefeated teams be treated?

Reasonable people can disagree about those questions. And the model has limitations. It cannot know what would have happened in games that were never played. It cannot completely resolve weak connections between schedules. It doesn't estimate how a roster injury might change next week's performance, because that isn't the question the merit ranking is designed to answer.

But I don't think perfection is the appropriate standard. **Transparency is.** Every assumption is stated. Every game contributes through a defined mathematical rule. There are no team- or conference-specific priors baked into the model. Instead, we can identify why one team ranks above another, how its schedule affected the comparison, and how uncertain that ordering is all based on records. The results on the field are all that matter. 

And if someone disagrees with a fairness rule, they can change the relevant threshold or on/off setting themselves and see exactly which teams move, which comparisons triggered the movement, and which are still protected. The Bayesian model remains the same; the changed ranking reflects a different, openly stated decision about what counts as fair. That's a much more productive argument than debating what thirteen committee members might have been thinking behind closed doors.

At the end of the day, college football teams play games. They win, they lose, and they produce scores against real opponents. Those results should determine what they've earned.

**My CFB Margin of Merit Rankings are my attempt to do exactly that: let the season speak for itself, use statistics to interpret what it tells us, and be transparent about everything we still don't know.**
