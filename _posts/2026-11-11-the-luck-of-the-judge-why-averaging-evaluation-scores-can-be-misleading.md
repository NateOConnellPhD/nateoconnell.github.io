---
example: false
published: true
date: 2026-11-11
tags: []
title: "The Luck of the Judge: Why Averaging Evaluation Scores Can Be Misleading"
---
I recently led the poster award competition at the 2026 ASA Statistical Learning and Data Science (SLDS) Conference. I had 40 award-eligible posters, needed to recruit judges and assign evaluations, and ultimately had to select three award winners and two honorable mentions.

The obvious approach was to randomly assign a few judges to each poster, collect their scores, and rank the posters by their averages. Simple enough. This is pretty much the standard way of running a judged competition of any types

But I’m a statistician, and that bothered me.

Anyone who has participated in academic peer review knows that reviewers differ considerably in their expectations and scoring tendencies. Some are generous with high scores and only use the top half of the scoring range. Others use the entire range, and seem to reserve the highest scores for research that fundamentally changes the field. Even with a common rubric, there’s no guarantee that two reviewers interpret a score of 4 or 5 the same way.

With only two or three evaluations per poster, it seemed obvious to me that reviewer heterogeneity could be a real problem. A student with an excellent poster who gets bad luck of the draw with an overly critical reviewer may be unfairly scored in aggregate

What started as a fairly straightforward responsibility on the organizing committee for this conference quickly became an exercise in experimental design, hierarchical modeling, and Bayesian decision-making. Because apparently I can’t just organize a poster competition without turning it into a statistical problem.

1. The problem with naive averaging

Let $$T_{ij}$$ denote the total score assigned to poster $$i$$ by reviewer $$j$$, and let $$\mathcal J_i$$ be the set of reviewers assigned to poster $$i$$.

The naive estimator is simply

$$
\bar T_i = \frac{1}{|\mathcal J_i|}
\sum_{j\in\mathcal J_i}T_{ij}.
$$

The problem is that $$T_{ij}$$ reflects both the poster and the reviewer.

If reviewers differ in their scoring severity, the average of two or three scores contains variation attributable to the specific reviewers assigned to the poster.

Randomization can help avoid systematic assignment bias, but it doesn’t eliminate this variability in the reviewer bias itself. Even when reviewer effects average to zero across all possible assignments, the particular 2 to 4 reviewers evaluating a particular poster by chance may be unusually generous or conservative.

A second issue is that reviews aren’t independent in the usual sense. Scores assigned by the same reviewer share that reviewer’s scoring tendencies.

But that dependence can be useful if we account for it. If two reviewers evaluate overlapping sets of posters, their scores provide information about differences in how they use the rubric.

This led to the first part of the problem: designing the reviewer assignments so that the available evaluations provide as much information as possible about both the posters and the reviewers.

2. Designing the judging assignments

After 3 separate blast emails to over 250 non-student attendees asking for poster judge volunteers, I ultimately recruited 28 judges for the 40 award-eligible posters. Each judge was assigned three required reviews, along with two additional recommended reviews if time permitted.

The resulting design provided 84 required evaluations, guaranteeing at least two independent evaluations per poster. If everyone completed all five assignments, I could obtain 140 evaluations.

Rather than assigning posters completely at random, I constructed a constrained incomplete block design.

Let $$A$$ denote the $$40\times 28$$ binary assignment matrix, where

$$
A_{ij} = I(\text{reviewer } j \text{ evaluates poster } i).
$$

For the required assignments, I imposed

$$
\sum_i A_{ij}=3, \qquad \sum_j A_{ij}\geq 2.
$$

But I wanted more than balanced coverage.

I wanted each reviewer to share posters with as many different reviewers as possible, rather than repeatedly overlapping with the same individuals.

To accomplish this, I imposed

$$
\boxed{
\sum_i A_{ij}A_{ij'} \leq 1, \qquad j\neq j'.
}
$$

This guarantees that no pair of reviewers is assigned to evaluate more than one poster together.

I also required the network of reviewers to be connected and excluded known conflicts of interest.

Why does that matter?

If the judging network contains disconnected groups, differences in scoring severity across those groups become difficult to distinguish from genuine differences in average poster quality. A connected design allows information about reviewer effects to propagate throughout the network.

As it turns out, there is also a formal statistical efficiency argument for this (thanks ChatGPT).

Under a homoscedastic additive model treating reviewer effects as nuisance parameters, the information matrix for adjusted poster comparisons is proportional to

$$
C(A) = \operatorname{diag}(r) - A\operatorname{diag}(k_j^{-1})A^\top,
$$

where $$r_i$$ and $$k_j$$ are the poster and reviewer assignment counts.

A natural A-optimality objective is

$$
\boxed{
\min_A \operatorname{tr}\bigl(C(A)^+\bigr),
}
$$

where $$C(A)^+$$ is the Moore–Penrose inverse.

I used constrained assignment generation and optimization to improve the design while preserving the coverage and overlap requirements. I didn’t actually prove global A-optimality, but I could verify the relevant combinatorial properties.

For the final design, the trace criterion decreased from 41.74 using only the required assignments to 14.64 with all optional assignments.

There’s actually a paper directly relevant to this problem: Niu and Rosenberger (2019) studied near-balanced incomplete block designs specifically for poster competitions.

The optional assignments also had a practical benefit: redundancy.

I deliberately distributed fourth reviews across different posters before allocating fifth reviews. If some judges didn’t complete their required evaluations, the optional reviews could help compensate for those missing scores.

So the design helped both statistically and operationally.

3. Modeling the evaluations

I developed a scoring rubric with four equally weighted criteria: Originality and Innovation, Significance and Potential Impact, Rigor, and Communication.

Each criterion was scored from 1 to 5, giving a total between 4 and 20.

My first thought was to model the total scores using a Normal hierarchical model. That would have been simple enough and computationally efficient, and probably not unreasonable either.

But why collect four separate ordinal ratings if I was just going to collapse them immediately?

The individual criteria provide additional information about how reviewers evaluate different aspects of the work. One judge might be particularly conservative when scoring rigor, while another might apply a much higher standard to originality.

So of course, I naturally settled on a hierarchical ordinal-probit model.

Let

$$
Y_{ijk}\in\{1,2,3,4,5\}
$$

denote the score assigned to poster $$i$$ by reviewer $$j$$ on criterion $$k$$.

I introduce an underlying latent assessment

$$
Z_{ijk}=\eta_{ijk}+\epsilon_{ijk}, \qquad \epsilon_{ijk}\sim N(0,1),
$$

with

$$
\eta_{ijk}=\mu+\alpha_i+\beta_j+\gamma_k+\delta_{ik}+\zeta_{jk}+\xi_{ij}.
$$

The terms have the following interpretations:

Term | Interpretation
--- | ---
$$\alpha_i$$ | Overall poster effect
$$\beta_j$$ | General reviewer scoring tendency
$$\gamma_k$$ | Criterion-specific location
$$\delta_{ik}$$ | Poster-by-criterion deviation
$$\zeta_{jk}$$ | Reviewer-by-criterion deviation
$$\xi_{ij}$$ | Reviewer–poster interaction

The reviewer–poster interaction is particularly interesting. It represents the possibility that a reviewer forms an overall impression of a particular poster that influences all four ratings.

The observed ratings are generated by discretizing the latent assessments through criterion-specific thresholds:

$$
Y_{ijk}=c \iff \tau_{k,c-1}<Z_{ijk}\leq \tau_{kc},
$$

so

$$
P(Y_{ijk}=c\mid\eta_{ijk})
= \Phi(\tau_{kc}-\eta_{ijk})-\Phi(\tau_{k,c-1}-\eta_{ijk}).
$$

I fix the latent residual variance at 1, use ordered criterion-specific cutpoints with the second threshold fixed at zero for identification, and force constraints to sum to zero on the reviewer-by-criterion deviations.

The random effects are assigned partially pooled Gaussian priors, for example,

$$
\alpha_i\sim N(0,\sigma_\alpha^2), \qquad
\beta_j\sim N(0,\sigma_\beta^2), \qquad
\xi_{ij}\sim N(0,\sigma_\xi^2),
$$

with corresponding priors for the criterion-specific deviations and inverse-gamma priors on the variance components.

The actual implementation used proper regularizing priors with variance hyperparameters decided on before observing the competition results.

Partial pooling is important. With only a handful of evaluations per reviewer and poster, unrestricted reviewer and interaction effects would be estimated extremely imprecisely.

And why probit instead of logit?

There is a highly sophisticated statistical reason for choosing the probit link.

It was easier to program in JavaScript.

Seriously.

With a probit model, I could use latent-normal data augmentation and a Gibbs sampler, with truncated-normal updates for the latent assessments and convenient Gaussian conditional updates for the random effects.

I could have used an ordered-logistic model, but the probit formulation made it easier to construct a computationally efficient sampler without requiring a separate statistical computing server.

(And by “I” here, I mean ChatGPT Astra. I don’t know JavaScript remotely well enough to do this in a reasonable amount of time. I had GPT translate the model from R to JavaScript, and results matched to 10^-4)

And you’re probably thinking why in the world I’d need to run this in JavaScript? Because I needed to have these scored that night, so I could let the winner know, and get them tickets to the banquet dinner the next night to receive their award. And I didn’t want to be up late.

I had built a mobile scoring app using Google Apps Script, with a personalized link for each reviewer. Judges could select their assigned posters, submit their four scores, and continue to the next poster. I already had built this so I could monitor scores coming in, in real time.

So I then had ChatGPT implement the Bayesian sampler in JavaScript, checked its calculations against an independent implementation in R, and integrated it into a separate Google Sheets dashboard. The dashboard would automatically rerun the posterior analysis as new evaluations arrived. I knew the winners as soon as the final reviews were submitted. As it turns out, some of these scores weren’t submitted until late that night anyway. One reviewer’s phone died and they couldn’t submit his scores until he got home. The conference was in Brooklyn. The poster session ended at 9, and he had to take a train home, so I was still up till midnight anyway waiting for final scores. Oh well.

So yes, the choice between probit and logit was partly determined by my desire to run an unnecessarily sophisticated Bayesian analysis inside Google Apps Script.

Sometimes practicality wins.

4. What exactly is the estimand?

I debated this in my head. Probably spent too much time on this if I’m being honest.

What does it mean to identify the “true” best three posters?

There is no objectively observable numerical measure of scientific quality. Different statisticians can reasonably disagree about which research contributions are most important.

Rather than estimating an abstract population-level quality parameter, I wanted to answer a more operational question:

What would the rankings have been if all 28 judges evaluated all 40 posters?

After all, these 28 judges volunteered their time, let’s make their collective predictive opinion the authority.

That would produce

$$
28\times 40 = 1{,}120
$$

evaluations.

Let $$Y_{ijk}^{\mathrm{full}}$$ denote the score that reviewer $$j$$ would assign poster $$i$$ on criterion $$k$$ under this hypothetical complete evaluation.

The finite-panel average for poster $$i$$ would be

$$
S_i^{\mathrm{full}} = \frac{1}{28}
\sum_{j=1}^{28}
\sum_{k=1}^{4}
Y_{ijk}^{\mathrm{full}}.
$$

These averages define the ranking that would result from the collective assessments of the actual judging panel.

The advantage is that differences in general reviewer severity would be balanced across posters automatically if every reviewer evaluated every poster.

The problem, of course, is that I couldn’t reasonably ask 28 people to evaluate 40 posters during a 90-minute session.

So I treated the unobserved evaluations as missing data and used posterior predictive imputation.

For each posterior draw, I retained the evaluations that were actually submitted and simulated the missing reviewer–poster ratings using the sampled model parameters.

Each draw therefore produced a possible completed panel of 1,120 evaluations.

I then calculated the complete-panel average for each poster and ranked all 40.

Repeating this procedure produced a posterior distribution over the rankings that would have resulted from a complete evaluation.

In particular,

$$
p_{i,3} = P\left(\operatorname{rank}(S_i^{\mathrm{full}})\leq 3\mid \mathbf Y_{\mathrm{obs}}\right).
$$

I also calculated $$p_{i,5}$$ and $$p_{i,10}$$ to be used as a tiebreaker.

One important assumption is that the missing evaluations can be predicted from the observed scores, assignment structure, and hierarchical model. If optional-review completion depends on the unobserved assessment itself, that assumption may fail. Likewise, a poster that never appeared is not simply an ordinary missing review.

Those limitations matter, particularly when interpreting the posterior probabilities.

5. How do the probabilities determine awards?

The competition recognized three award winners and two honorable mentions.

Rather than ranking posters by posterior mean scores, I ranked them by their posterior probability of belonging to the completed panel’s top three.

There’s a straightforward decision-theoretic justification.

Let $$\mathcal S$$ denote the three selected award recipients and $$\mathcal T_3$$ denote the top three under the fully observed panel.

Then

$$
\begin{aligned}
E\left[\left|\mathcal S\cap\mathcal T_3\right|\mid\mathbf Y_{\mathrm{obs}}\right]
&=
\sum_{i\in\mathcal S}P(i\in\mathcal T_3\mid\mathbf Y_{\mathrm{obs}})\\
&=
\sum_{i\in\mathcal S}p_{i,3}.
\end{aligned}
$$

Thus, selecting the three posters with the largest $$p_{i,3}$$ maximizes the posterior expected number of correctly identified top-three posters.

The next two posters in that same ordering received honorable mentions.

I also considered the severity of mistakes. Mistaking the fourth-ranked poster for the third seems relatively harmless. Awarding a poster that would rank 20th under a complete evaluation is considerably more concerning.

I therefore included a limited tie-breaking rule based on $$P(\text{Top 10})$$, with numerical safeguards to avoid reversing decisions based on negligible Monte Carlo differences.

To be clear, I established this model and selection rules before ever modeling the real evaluations. It was set before the conference poster session. There was no post-hoc model evaluation other than checking convergence.

6. Did any of this actually improve the selections?

This was the question I cared about in reality. The modeling was a fun thought experiment, but does it actually make a difference?

A more complicated model is not inherently a better model. I wanted to know whether hierarchical adjustment actually improved the ability to reproduce the complete judging panel’s decisions.

So of course I ran simulations in which I generated a fully saturated matrix of scores for every reviewer and poster. That gave me a known reference ranking.

I then concealed all but the evaluations specified by the incomplete assignment design, fitted the Bayesian model, and compared its selections against those obtained by simply averaging the observed scores.

I considered three broad scoring scenarios: moderate reviewer variability, heterogeneous reviewer preferences across scoring criteria, and closely matched posters with relatively subjective evaluations.

Bayesian adjustment versus simple averaging

The table shows the average number of the complete panel’s top-three posters correctly selected. The maximum possible is three.

Scenario | Reviews | Naive average | Bayesian model
--- | ---: | ---: | ---:
Moderate reviewer variability | 80 | 1.88 | 1.92
Moderate reviewer variability | 130 | 2.05 | 2.19
Different reviewer preferences | 80 | 1.62 | 1.75
Different reviewer preferences | 130 | 1.88 | 2.06
Closely matched posters | 80 | 1.09 | 1.26
Closely matched posters | 130 | 1.27 | 1.56

These results come from 160 simulated competitions per scenario, using an earlier ordinal hierarchical specification.

The results were encouraging. Not amazing, but better than doing nothing. After all, predicting a winner on only 2-4 reviews is a noisy problem and no model will be perfect.

Under moderate reviewer variability, hierarchical adjustment provided a relatively modest improvement. When reviewers differed more substantially or posters were closely matched, the improvement was larger.

And additional independent reviews generally helped both methods. More data yields better results. Who knew?

The benefit of the statistical model was not that it somehow recovered perfect rankings from inadequate data. It was that, under several plausible scoring mechanisms, it improved agreement with the complete panel while providing a posterior distribution that quantified the uncertainty in the remaining comparisons.

How bad were the mistakes?

I also wanted to distinguish relatively minor mistakes from serious ones.

For example, how often would the selected three award recipients include at least one poster ranked outside the fully evaluated panel’s top ten?

In a separate simulation with 75 competitions per scenario, the results with only the required reviews were:

Scenario | Naive average | Bayesian model
--- | ---: | ---: | ---:
Moderate variability | 12.0% | 5.3%
Different reviewer preferences | 32.0% | 22.7%
Closely matched posters | 61.3% | 54.7%

Here, the Bayesian analysis generally reduced the frequency of severe errors.

But the results also reveal an important limitation. When posters were very similar and reviewer judgments were highly variable, neither method could reliably recover the complete-panel rankings.

No statistical model can manufacture information that wasn’t collected.

Why the additional model terms?

I also compared simpler and more flexible ordinal models.

In simulations with reviewer heterogeneity, the initial ordinal model sometimes produced posterior predictive intervals that were too narrow.

Adding reviewer-by-criterion effects alone did not fully fix the issue. Including a shared reviewer–poster interaction improved the calibration of predictive uncertainty.

In one exploratory simulation, nominal 95% predictive-interval coverage increased from approximately 90% to 94% after including that interaction. So that’s a small statistical win.

And that was the main justification for the final expanded model.

Interestingly, the added complexity did not consistently improve the number of correctly selected winners. Its principal benefit was more accurately representing uncertainty in unobserved evaluations.

I also investigated a ten-point scale, and asking reviewers to rank their assigned posters in order. None provided a consistent enough improvement in the exploratory simulations to justify complicating the scoring process, at least in my limited simulations. So for simplicity, I kept the original four-criterion, five-point rubric.

7. What happened in the actual competition?

I ultimately collected 90 evaluations, well short of the 140 possible assignments.

Not every scheduled poster appeared, and some reviewers didn’t complete all of their assignments. Fortunately, the extra recommended reviews provided some redundancy against missing evaluations. Every poster received at least 2 reviews.

I fitted the prespecified model using four independent MCMC chains, retaining 16,000 posterior parameter draws and generating 32,000 completed-panel realizations.

The model ran in approximately 51 seconds in JavaScript. The maximum reported split-R-hat values were approximately 1.002 for the poster scores and 1.004 for the variance components.

The resulting posterior estimates for the leading seven posters are shown below. Posters are identified only by their final model rank, not by their actual presentation numbers or identities.

Model rank | Posterior mean score | P(Top 3) | P(Top 5) | P(Top 10)
--- | ---: | ---: | ---: | ---:
1 | 16.97 | 78.0% | 90.0% | 98.2%
2 | 16.70 | 71.0% | 85.9% | 97.2%
3 | 15.85 | 41.0% | 63.1% | 88.7%
4 | 15.41 | 23.2% | 47.3% | 84.5%
5 | 15.28 | 18.5% | 42.6% | 82.6%
6 | 14.81 | 14.1% | 31.1% | 66.7%
7 | 14.78 | 12.2% | 28.8% | 66.5%

Ranks 1–3 received awards, and ranks 4–5 received honorable mentions.

I found the posterior probability reassuring. To be honest, I was a little nervous, but the separation made the selection of winners non-ambiguous.

The first two recipients had substantially higher top-three probabilities than the rest. The third award recipient had a 41% probability of belonging to the complete panel’s top three, compared with approximately 23% for the next candidate.

That’s a difference of nearly 18 percentage points, with a Monte Carlo standard error for the difference of approximately 0.7 percentage points.

The final honorable-mention position was closer in top-three probability. But the fifth-ranked poster also had a notably higher probability of belonging to the complete panel’s top ten than the sixth-ranked poster: approximately 83% versus 67%.

So while I certainly couldn’t claim to know the objectively correct ordering, the final selections were reasonably well separated under the prespecified posterior decision rule.

The top-ten probabilities were especially reassuring. All five selected posters had posterior probabilities above 80% of belonging to the fully evaluated panel’s top ten.

One last reassurance

After everything was finished, out of curiosity, I ignored the Bayesian analysis entirely and simply ranked the posters by their observed average total scores.

All three award winners were identical under the naive averages and the Bayesian model. Four of the five recognized posters agreed.

The only disagreement was the final honorable mention.

That one disagreement was actually the most interesting example of the model doing what I had hoped. The poster selected by the Bayesian model received scores of 17, 12, and 18, for a raw average of 15.67. The poster favored by naive averaging received 15 and 17, averaging 16.00. A difference of only a third of a point, but enough to change the final honorable mention.

When I looked at who assigned those scores, the three reviewers evaluating the Bayesian-selected poster had average total scores of 10.6, 13.0, and 15.0 across their own submitted evaluations. The two reviewers evaluating the naive-average choice averaged 14.0 and 14.3. Now, these aren’t unbiased estimates of reviewer severity, since each reviewer evaluated different posters. But they illustrate exactly why I was worried about comparing raw averages in the first place. The scoring environments were not necessarily comparable.

And this wasn’t trivial reviewer heterogeneity. The fitted model estimated standard deviations of approximately 0.66 for overall reviewer severity, 0.42 for reviewer-by-criterion effects, and 0.78 for reviewer–poster impressions, all on the latent probit scale.

After accounting for that variation and predicting the completed judging panel, the poster with the lower raw average had an 18.5% posterior probability of ranking in the top three and an 82.6% probability of ranking in the top ten. The alternative had corresponding probabilities of 12.2% and 66.5%.

I can’t claim that this proves the Bayesian selection was correct. But it was precisely the type of situation I built the model to address: two posters evaluated by different reviewers, where the raw scores alone don’t tell the whole story.

I actually liked this result.

After spending all that time on constrained incomplete block designs, ordinal-probit models, reviewer interactions, posterior predictive imputation, and implementing an MCMC sampler in JavaScript, the final selections were mostly the same as simply averaging the scores.

But that’s fine with me. First, this was fun for me. Second, the strong agreeability is not evidence that the statistical work was pointless.

The simulations demonstrated circumstances in which reviewer adjustment meaningfully reduced errors. The actual analysis quantified uncertainty that averaging alone could not provide. And the agreement with the naive approach showed that the final decisions weren’t dependent on aggressive modeling adjustments.

In other words, I got the robustness check I was hoping for.

8. What I took away from this

The original goal was simple: select five award recipients from a group of research posters.

The statistical problem turned out to be far more interesting.

When objects are evaluated by different subsets of human reviewers, the observed score depends on both what is being evaluated and who happens to evaluate it.

Averaging the scores doesn’t eliminate that distinction.

Thoughtful experimental design can improve the information available from a limited number of evaluations. Hierarchical modeling can account for systematic reviewer differences. And Bayesian posterior prediction can express uncertainty about the decisions that would have resulted from a more complete evaluation.

None of this guarantees that the selected winners are the objectively best researchers or that their work is objectively superior. That was never a realistic goal. But at least I know I tried to do it as fairly as possible, and hopefully something all the young statisticians presenting could appreciate.

The objective was to develop a process that was transparent, statistically defensible, and reasonably robust to the particular reviewers assigned to each poster.

I think the approach accomplished that.

And there are broader applications here. Grant reviews, manuscript reviews, faculty hiring, academic awards, and student evaluations all involve similar problems with heterogeneous reviewers and incomplete comparisons.

Whenever the same item could receive different scores depending on who evaluates it, the scoring mechanism itself becomes part of the statistical problem.

The lesson isn’t that averaging scores is always wrong. It’s that an average is only as meaningful as the process that generated the scores.

And sometimes, what looks like a simple administrative task turns out to be an excuse to build a Bayesian hierarchical model.

I’m also working on generalizing the Google Apps Script application into something other conference organizers could use. The idea is to upload spreadsheets of posters and reviewers, specify the judging rules and scoring rubric, and have the system generate the assignments, personalized scoring forms, and Bayesian dashboard automatically. If anyone is interested, I’m happy to share what I’ve built.

And I’ll be organizing the SLDS poster competition again in 2028. If you’re planning to attend, please consider volunteering as a judge! I promise you won’t have to run the Gibbs sampler yourself.

⸻

References

* Niu, X., & Rosenberger, J. L. (2019). Near-Balanced Incomplete Block Designs, With an Application to Poster Competitions. The American Statistician, 73(2), 159–164.
* Albert, J. H., & Chib, S. (1993). Bayesian Analysis of Binary and Polychotomous Response Data. Journal of the American Statistical Association, 88(422), 669–679.
* Rubin, D. B. (1976). Inference and Missing Data. Biometrika, 63(3), 581–592.
* Vehtari, A., Gelman, A., Simpson, D., Carpenter, B., & Bürkner, P.-C. (2021). Rank-Normalization, Folding, and Localization. Bayesian Analysis, 16(2), 667–718.
