---
title: "Random Forests as Statistical Procedures: Design, Variance, and Dependence"
kind: Preprint
area: "Methods & theory"
year: 2026
authors: "Nathaniel S. O’Connell"
venue: "arXiv"
summary: "Variance and dependence in random forests, including the uncertainty that remains as the number of trees grows."
featured: true
order: 1
published: true
example: false
link: "https://arxiv.org/abs/2602.13104"
---
We develop a finite-sample, design-based theory for random forests in which each tree is a randomized conditional predictor acting on fixed covariates and the forest is their Monte Carlo average. An exact variance identity separates Monte Carlo error from a covariance floor that persists under infinite aggregation. The floor arises through two mechanisms: observation reuse, where the same training outcomes receive weight across multiple trees, and partition alignment, where independently generated trees discover similar conditional prediction rules. We prove the floor is strictly positive under minimal conditions and show that alignment persists even when sample splitting eliminates observation overlap entirely. We introduce procedure-aligned synthetic resampling (PASR) to estimate the covariance floor, decomposing the total prediction uncertainty of a deployed forest into interpretable components. For continuous outcomes, resulting prediction intervals achieve nominal coverage with a theoretically guaranteed conservative bias direction. For classification forests, the PASR estimator is asymptotically unbiased, providing the first pointwise confidence intervals for predicted conditional probabilities from a deployed forest. Nominal coverage is maintained across a range of design configurations for both outcome types, including high-dimensional settings. The underlying theory extends to any tree-based ensemble with an exchangeable tree-generating mechanism.
