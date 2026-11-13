---
example: false
published: true
date: 2026-11-13
tags: []
title: "A Theory of Cross-Validation Variance: How a Simple Clinical Question turned into a Statistical Theory"
description: What began as a clinical prediction question in 2020 became a six-year investigation into the uncertainty of cross-validation. Here's the story behind our new variance theory, why longstanding recommendations about cross-validation disagree, and how a simple change in mathematical perspective helped resolve fundamental questions about K-fold, Monte Carlo, and leave-one-out cross-validation.
---
*How a clinical prediction problem led to a new understanding of cross-validation, its uncertainty, and the longstanding debate over which methods work best.*

In 2020, a clinical investigator came to me with what seemed like a straightforward question. He had four additional cardiac MRI measurements from patients with pulmonary embolism and wanted to know whether they significantly improved our ability to predict clinical deterioration (a binary composite outcome defined by things like "death, cardiac arrest, etc. within X number of days).

So, I built prediction models with and without those variables, using logistic regression and random forests. The random forests performed substantially better, so I focused on comparing two random forest models using cross-validated AUC. The AUCs were different. But were they *significantly* different? I didn't have an answer for that question, because a method didn't exist to answer that question.

The obvious response to this statement from anyone who's worked in building prediction models is probably, "Why not just use DeLong's test?" Here's why: DeLong's test is designed to compare the AUCs of two fixed models evaluated on the same independent test sample. It accounts for sampling variability in that test sample, but treats the fitted models themselves as fixed. It doesn't account for the additional uncertainty introduced by drawing a different training dataset and refitting the models. Cross-validation complicates this even further. Rather than evaluating two fixed models, we're repeatedly fitting new models on overlapping subsets of the same observations. Each observation contributes not only to evaluating predictive performance, but also to training the models used to predict other observations. DeLong's test doesn't account for this dependence or the variability of the complete cross-validation procedure.

Ultimately, neither the clinical investigator nor I was particularly interested in whether two specific fitted models produced different AUCs on our particular dataset. We wanted to answer a much broader scientific question: **Across the population of patients with pulmonary embolism, do these four cardiac MRI measurements genuinely improve our ability to predict clinical deterioration?** Answering that question required comparing the expected predictive performance of two learning procedures, not simply two sets of predictions from fixed models.

To make that comparison, I needed to quantify the uncertainty of the entire cross-validation procedure, including the variability arising from sampling patients from a larger population, repeatedly fitting models, and evaluating their predictions. The variation introduced by randomly assigning observations to different folds was only one component of that uncertainty. What I needed was a general mathematical characterization of the sampling variance of cross-validated performance estimates, and ultimately, the variance of the difference between two such estimates. At the time, a general theory that would allow me to do that did not exist. 

That question stuck with me for years.

## A surprisingly unsettled problem

Cross-validation is one of the most widely used procedures in statistics and machine learning. Yet despite decades of research, there is still considerable ambiguity about how best to perform it.

Should we use five-fold or ten-fold cross-validation? Is leave-one-out better or worse? Should we repeat $$K$$-fold cross-validation, or use Monte Carlo cross-validation (MCCV), where we repeatedly generate independent random training and validation splits? What about the bootstrap?

You can find different recommendations throughout the literature, none of which consistently point to the same answer with much theoretical justification.

For example, [Kohavi's influential 1995 study](https://www.ijcai.org/Proceedings/95-2/Papers/016.pdf) helped establish stratified ten-fold cross-validation as a practical default. The widely used [scikit-learn documentation](https://scikit-learn.org/stable/modules/cross_validation.html) cautions that leave-one-out can have high variance because its training sets overlap so heavily, generally favoring five or ten folds.

Other studies, typically based on empirical evidence, recommend repeated $$K$$-fold or MCCV, arguing that averaging over repeated random partitions provides more stable estimates. I myself, had reasoned: if I just run MCCV (i.e. repeated split sampling at the sample training:validation split ratio, where each fold is generated independently) hundreds of times), that has to be sufficient for averaging out the sampling variability, right?

The comparison between ordinary $$K$$-fold and MCCV is particularly interesting. Repeated random splitting gives us more flexibility in choosing training fractions and can reduce dependence on any particular partition. But ordinary $$K$$-fold ensures that every observation contributes equally to validation. Which advantage matters more for variance?

And even after choosing $$K$$-fold, what is the optimal number of folds?

Part of the ambiguity arises because different studies are answering different questions. Selecting the best model isn't the same as estimating its performance. Minimizing bias isn't the same as minimizing variance. And variability among individual fold scores isn't the same as the sampling variance of the completed cross-validation estimate.

The [review by Arlot and Celisse](https://arxiv.org/abs/0907.4728) illustrates just how complicated the literature becomes when these different objectives are considered.

But even when focusing specifically on variance, general answers have been difficult to establish. Much of the existing theory concerns particular models, loss functions, or cross-validation procedures.

**For something statisticians and data scientists use so routinely, we still lacked a general explanation for what makes one cross-validation design more variable than another.**

## Trying to find an answer empirically

Between 2022 and 2024, I spent considerable time investigating these questions through simulations and benchmarking studies. I presented some of this work in an invited session at JSM 2022. My summer research intern in 2024, Jerry John Rawlings Mensah
(https://www.linkedin.com/in/jjrmensah/), spent the summer working on a benchmarking study focused on studying cross-validation methods. 

I compared $$K$$-fold and MCCV across different datasets, sample sizes, training fractions, and numbers of repetitions. The results were frustratingly inconsistent.

Single train/test splits were generally much more variable, which wasn't surprising. But comparisons between MCCV and $$K$$-fold were less straightforward. Sometimes one performed better, sometimes the other. At larger sample sizes, differences often became difficult to distinguish. I still had questions on how this depended on the model/learner itself, the metric being cross-validated, the data structure... 

It looks like, in aggregate, some form of k-fold or repeated k-fold was likely better, but I couldn't identify a general principle explaining the results.

I was trying to identify the best procedure by comparing its outputs, without first understanding the mathematical mechanism determining their variance.

## The insight: Stop thinking about folds

About a year ago, in November 2025, something occurred to me. I remember I was driving my son to daycare thinking about the problem, had a lightbulb moment, and typed it into my notes on my phone as soon as I parked.

What if, instead of expressing cross-validation as an average of fold-level results, I represented it as a weighted sum of contributions from individual observations?

For a metric like mean squared error, we can write

$$
\widehat R_{\mathrm{CV}}
=
\sum_{i=1}^{n}v_i\ell_i,
$$

where $$\ell_i$$ represents an observation's average held-out loss and $$v_i$$ represents its share of the total validation evaluations.

This is a simple change in representation, but it exposes a level of detail that allows for further understanding. In ordinary $$K$$-fold cross-validation, every observation is held out exactly once, so every observation has the same validation weight. In MCCV, some observations may be selected for validation more frequently than others. Their weights aren't necessarily equal.

But here's where things became interesting: **the weights themselves depend on the random assignments of observations to training and validation sets. What if we explicitly represented that randomness?**

We can define an indicator variable,

$$
I_{ir}=
\begin{cases}
1 & \text{if observation }i\text{ trains in split }r,\\
0 & \text{if observation }i\text{ is validated in split }r.
\end{cases}
$$

Now collect these indicators into a matrix, $$I=(I_{ir})$$, representing the entire cross-validation design. The design is a probability distribution over this matrix.

The number of times an observation is validated is simply $$N_i=\sum_r(1-I_{ir})$$, and its validation weight becomes

$$
v_i(I)=\frac{N_i}{M}
=\frac{\sum_r(1-I_{ir})}{M},
$$

where $$M$$ is the total number of validation evaluations.

This was the important realization. **We've represented the randomness of cross-validation through a well-defined random variable, $$I$$. And because we have a random variable, we can condition on it.**

Conditional on $$I$$, every training and validation assignment is fixed. We know which observations train each model, which are evaluated, and how often. The data themselves remain random draws from the population.

We can therefore apply the law of total variance, treating the cross-validation design as a random variable separately from the sampled observations.

But there was another realization embedded in this representation: **every observation influences cross-validation in two distinct roles.** First, it contributes directly when held out for validation. Second, it contributes indirectly through training, because it influences the fitted models and therefore the predictions made for other observations.

Just as the validation weights are determined by $$I$$, we can define training weights that describe how frequently each observation contributes to fitting the models.

These two influences can be correlated. They might reinforce one another or partially cancel. And the covariance between them matters for the variance of the completed cross-validation estimate.

We now had something we hadn't had before: a way to represent cross-validation as a function of the sampled observations and an explicitly defined random inclusion structure, with weights describing how observations contribute through training and validation.

That gave me a starting point for deriving its variance.

## Three paths to the same theory

My first approach was relatively simple: apply the law of total variance to this representation, conditioning on the random inclusion structure $$I$$.

$$
\begin{aligned}
\operatorname{Var}(\widehat R_{\mathrm{CV}})
={}&
\mathbb E_I\left[
\operatorname{Var}(\widehat R_{\mathrm{CV}}\mid I)
\right]\\
&+
\operatorname{Var}_I\left[
\mathbb E(\widehat R_{\mathrm{CV}}\mid I)
\right].
\end{aligned}
$$

For fixed-size cross-validation designs under the usual independent sampling and symmetry assumptions, the second term is zero. Regardless of which observations happen to be assigned to which folds, the expected performance estimate is the same because every model trains on the same number of observations.

This meant I could focus on characterizing the variance **conditional on the splitting assignments**, treating the design as fixed while allowing the sampled observations to vary.

I began expanding the variance and covariance terms associated with the weighted observation-level losses, accounting for how each observation contributes through validation and through training. These were relatively straightforward calculations through some basic algebra, and revealed important relationships between cross-validation designs, including why the balance of observation weights matters and how the covariance between training and validation influences affects variance. I was able to reduce this to a variance identity that showed the validation weights mattered, and that minimizing them minimzied the first order variance, but the training weights and correlations were still not completely clear in the math. 

I then explored the same problem using **influence functions**, approaching it from the perspective of how individual observations affect the completed cross-validation estimate.

This recovered the same first-order relationships through a different mathematical approach. The agreement was reassuring, particularly because the original variance expansions and the influence-function calculations had arrived at the same conclusions independently.

But I wanted something more general. With each of the two approaches, I had to make higher order rate assumptions assuming stability criteria that couldn't necessarily be proved for many ML algorithms we use. This worked for estimators like logistic regression, but didn't necessarily hold for Random Forests. For more complex learning algorithms, interactions involving multiple observations may contribute meaningfully to variance. I didn't want general theory that required assuming those contributions were negligible, I wanted a theory for the collection of learning procedures people use. 

That eventually led me to the **Hoeffding decomposition**.

A Hoeffding decomposition separates the variation in a statistic into orthogonal components associated with individual observations, pairs of observations, triples, and so on, extending through every order of interaction. This provided the structure I needed to make this work.

Conditional on $$I$$, the observations are independent, even though the cross-validation estimate is a complicated function of them. We can therefore use a Hoeffding decomposition to characterize how much of its variance comes from individual observations and how much comes from interactions among multiple observations.

The earlier variance expansions and influence-function derivations had revealed the same underlying mechanisms. The Hoeffding decomposition recovered those relationships, but allowed us to expand them systematically across every order. And crucially, the decomposition is exact. We didn't have to assume that higher-order interactions vanished.

We could also reverse the conditioning in the law of total variance, conditioning on the sampled dataset rather than the inclusion structure. That gives the complementary distinction between *sampling variance*, arising from drawing different datasets, and *split noise*, arising from different training and validation assignments within the same dataset.

**That's why we ultimately chose the Hoeffding decomposition as the foundation for the paper. Not because the earlier derivations were wrong, but because it unified their conclusions within an exact framework capable of characterizing variance across all orders of interaction.** You can derive the first order identity of the CV variance to algabraically equivalent representations in 3 different ways, but the Hoeffding decomposition provide the most general and complete approch. 

The resulting [paper, coauthored with Jaime Speiser](https://arxiv.org/abs/2611.14463), establishes an exact finite-sample variance identity for cross-validation. The identity itself requires neither model stability nor higher-order rate assumptions.

Those additional assumptions become relevant when deriving particular optimality results, but not when establishing the identity itself.

## What the theory reveals

**1. Sampling variance and split noise are different things.**

Sampling variance reflects the uncertainty from having collected one particular dataset. Split noise is the additional variability caused by randomly partitioning that dataset. Repeated cross-validation reduces split noise, but it cannot eliminate sampling variance. Running cross-validation 1,000 times on the same dataset does not give us the equivalent of 1,000 independent datasets.

**2. Balanced designs have a fundamental variance advantage.**

At a fixed training fraction, the exchangeable cross-validation designs we study share the same sampling variance. They differ in the additional noise introduced by splitting. Ordinary $$K$$-fold is balanced: every observation receives equal validation and training weights. MCCV and standard bootstrap cross-validation generally introduce imbalance.

We establish the first-order variance optimality of $$K$$-fold among fixed-size cross-validation designs at the same training fraction, under the relevant conditions. This provides a mathematical explanation for an important distinction between cross-validation procedures, rather than relying only on empirical comparisons. Higher order optimality can be extended when k-fold is permuted to ensure balance in pairs or higher combinations of observations, although computationally this becomes quite heavy. 

**3. More folds do not necessarily mean greater variance.**

Perhaps the most surprising result concerns the choice of $$K$$.

One longstanding argument against leave-one-out cross-validation is that its training sets overlap almost completely, creating highly correlated prediction errors and therefore high variance. But dependence between individual prediction errors doesn't, by itself, determine the variance of their average. We show that under appropriate conditions, **the leading variance of $$K$$-fold cross-validation doesn't depend on $$K$$**.

Increasing $$K$$ changes the training-set size and higher-order contributions, but not that common leading variance. Under additional assumptions about the learner and how variance changes with training size, we further show that leave-one-out minimizes variance within the $$K$$-fold family.

This doesn't mean leave-one-out is universally optimal for every learner or objective. In fact, in follw-up work that is under way, I am working to characterize when this is and isn't true. But it challenges the idea that greater training-set overlap necessarily produces a more variable estimate. And in this follow-up work, LOO optimality is largely tied to model stability -- unstable models like single decision trees, or even LASSO on low signal data, can in fact inflate the variance as $$K$$ approaches $$n$$, but not because of the overlap in the training sets as conventionally thought. This work will be published and discussed at a later date. 

**4. The performance metric matters.**

Our theory also covers pairwise metrics such as AUC.

Unlike MSE, which averages losses over individual observations, AUC evaluates case–control pairs. Ordinary $$K$$-fold AUC evaluates only pairs appearing together in the same validation fold, introducing additional variability from incomplete pair coverage. The theory explains why paired designs, including leave-pair-out cross-validation, can address this problem.

## Returning to the original question

Beyond the exact variance identity, our paper establishes asymptotic normality using the full variance, including higher-order contributions, under conditions that don't require conventional model stability or the disappearance of those higher-order terms.

Together, these results provide a general theoretical foundation for inference on cross-validated performance.

Knowing the mathematical identity for variance and consistently estimating that variance from an observed dataset are different challenges. A complementary paper we're preparing develops a consistent estimator that can be applied in practice.

The broader goal is to answer questions like the one I encountered in 2020: not just whether one model has a higher cross-validated AUC, but how confidently we can conclude that its predictive performance is genuinely better.

Looking back, what's most satisfying is that the breakthrough came from changing how I represented the problem. For years, I'd been comparing cross-validation procedures without fully understanding what created their variance. Once I stopped thinking about folds and started thinking about how observations contribute through both training and validation, the mathematical structure began to emerge.

**Cross-validation variance isn't determined by training-set overlap alone. It's determined by how observations influence the entire procedure, how those influences covary, and how the resampling design distributes them across the data.**

That conceptual shift became the foundation for a year of mathematical work—and a much clearer understanding of a question that had been bothering me for six years, and the literature more broadly for decades. 

---

**Paper:** O'Connell, N. S., & Speiser, J. L. (2026). [*A Theory of Cross-Validation Variance*](https://arxiv.org/abs/2611.14463). arXiv:2611.14463.
