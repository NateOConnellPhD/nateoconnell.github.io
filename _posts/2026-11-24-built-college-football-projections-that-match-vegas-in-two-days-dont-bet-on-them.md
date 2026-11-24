---
example: false
published: true
date: 2026-11-24
tags:
  - Bayesian Modeling
  - Sports
  - Gambling
  - Prediction
  - Projection
  - CFB
  - Football
  - Spread
comments: true
title: Built College Football Projections That Match Vegas in Two Days. Don't Bet on Them.
description: I built a college football projection model from public data, and it lands within a half of a point of the Vegas lines. What that shows is how much uncertainty sits behind every number, why even a model that matches Vegas still loses to the house, and why the way sports betting has flooded the game is a public-health problem.
---
## Why I built this

I don't gamble. I hate how pervasive gambling advertisements have become in sports. I'm not morally opposed to gambling or necessarily against its legality. What one chooses to do with their personal life is their business. But just like with cigarettes, I'm opposed to its public advertisement and promotion in its current form. I honestly think it's a growing public health crisis waiting to burst.

So I build statistical models for a living, and I wanted to answer one question: with only public data, could I build a college football model as good as the sportsbooks' lines? And how quickly with modern tools?

The answer: Pretty much, yes. And in about two days using Claude to augment the work. And what that model shows is the best argument I know against betting on those lines.

## What I built

Last week I posted my [College Football Ranking system](https://nateoconnell.com/blog/2026/11/20/college-football-has-a-rankings-problem-so-i-built-my-own/). Admittedly that is something I had been building in my free time and thinking through on-and-off for months. The model is a Bayesian rating system that only uses wins, losses, and score margins from the current season, and it uses a Bayesian network to estimate merit scores to rank teams based on their on-field performance over the season. This laid the foundation for turning this into a projection model, for power-rating teams and predicting lines for upcoming games.

I gave my model to Claude, and then started building it out further. Every team has a strength, in points against an average FBS team on a neutral field, and every game's margin is the difference in strength plus a home edge plus noise. I then added a bit more data useful for projection, that I don't think matters for rankings.

These are the few components that do most of the work:

- Strength drifts week to week, so a team that fades is rated on where it is now, not on what it did in September.
- Every stadium gets its own home edge, learned from three prior seasons.
- Each team starts with a preseason expectation built from last season's rating, the 247 talent composite, the AP preseason poll, returning production, the recruiting class, coaching changes and the transfer portal. As games come in, they take over.
- A second Bayesian model values every quarterback from every dropback since 2021, separating him from his line, his receivers and the defenses he faced. When a team changes starters, the line moves.

Everything comes from public data: play-by-play from cfbfastR and CollegeFootballData. Every forecast is refit each week using only games played before it. I built it on the 2023–25 seasons, froze the core model, and ran 2026 untouched. The quarterback piece came later and was backtested the same way and was found to help a bit. For example, Ohio State losing Julian Sayin moves their line by ~7 points (more on that later).

## How close does it get to the Sports Books?

Over four seasons, the model misses the final margin by 12.3 points on average. The opening line across the sports books misses by 12.1 and the closing line by 12.0. This model is within the margin of error of Vegas odds.

| 2023–26, 3,332 FBS games | Average miss (points) | Within 3 | Within 7 | Within 10 |
| --- | --- | --- | --- | --- |
| My model | 12.3 | 16.7% | 35.6% | 48.6% |
| Opening line | 12.1 | 17.0% | 37.5% | 50.4% |
| Closing line | 12.0 | 17.5% | 37.8% | 50.3% |

They're close, and those numbers look worse than they actually are. And that gap isn't spread evenly. In 2026, the clean out-of-sample test, my model missed by 12.4 against 12.0 for the opening line, and 11.8 for the closing, and most of that came in the first three weeks, where it trailed the closing line by more than a point. From week 9 on, my model beats both lines: 12.27 against 12.40 for the close and 12.44 for the opener.

The early gap is information (or lack thereof), not my method. Before any games are played, the books and the bettors who move their lines know depth charts, camp battles, how good the transfers really are, and who's back on defense and the offensive line. My preseason inputs are team-level public numbers, and the public returning-production data only covers offense.

During the season, the books price in every injury and suspension; my model only adjusts for the starting quarterback. And the closing line isn't one oddsmaker's guess. It's the opener after the sharpest bettors have moved it with their money.

That's why I think the last couple of percentage points are closable. With more time and paid data (player-level charting and grades, snap counts, depth charts, injury reports), the model could see most of what the market sees in that early season. That's more time and thought and testing, not a weekend directing Claude from my phone, but the gap is mostly a data problem, not a modeling one.

## The uncertainty is the story

Look at the within-7 column again. The sharpest number in sports, the closing line, lands within a touchdown of the final margin 38% of the time. Half the time it's off by more than 10.

That isn't a flaw in the line. Each team gets about 12 possessions, each ending in 0, 3 or 7 points, and a couple of them going the other way swings the margin by two scores. 95% of results land within roughly 30 points of the line, for both my model and for the books. Even a line that knew every team's true strength exactly would land within 7 only about 4 times in 10.

Individual team scores are no better. In 2026, the books' implied team scores (from the spread and the over/under) missed by 8.5 points on average. Teams expected to score 24 to 28 actually scored anywhere from 6 to 46, 95% of the time.

This weekend my model has UCLA beating USC by 3 or 4, with UCLA's own score anywhere from about 7 to 49. That range isn't sloppy modeling. That's football.

## The edge that disappeared

This is the part that should worry anyone who thinks they've found a system. In the 2023–25 backtest, a simple rule stood out: when my model liked the favorite by 3 or more points more than the opening line did, or the underdog by 6 or more, the result landed on the model's side 59% of the time over 600 games. Break-even at standard odds is 52.4%. That looks like easy money.

In 2026, with the model frozen, the same rule hit 50% over 235 games. The share of the model's disagreement with the opener that showed up in the results went from 54% in 2023 to 37%, then 22%, then zero. Meanwhile the openers kept getting sharper: their average miss fell from 12.21 points in 2023 to 11.98 in 2026.

The thresholds were picked on those same three seasons, and the market kept learning. The model itself wasn't overfit. It's a Bayesian model that learns as the season goes, and its 2026 shortfall came from early-season information, not tuned settings. But the rule was a slice picked out of three seasons, and small samples make slices look better than they are.

## Why matching Vegas still loses

The books don't need to out-predict you. At standard odds of −110, you risk $110 to win $100, so you need to win 52.4% of your bets to break even. A model exactly as good as the line wins about half, and at 50% you lose about 4.5 cents of every dollar you bet. Forever.

To make money you have to beat the closing line by enough to clear that gap. With about 15 points of game-to-game noise, it takes hundreds of games just to know whether you are. I built something about as good as Vegas in two days. I did so by giving Claude Opus 5.5 my Bayesian framework for merit rankings, giving it direction and free-use of several agents, and giving it directions on what additional data to pull in, how to use that data, and what to look for. It made mistakes along the way. My level of statistical understanding probably allowed me to do this faster than most people could. Claude makes mistakes, and it did here. My background in Bayesian statistics and prediction model development allowed me spot errors, make modeling decisions, and direct it quite quickly. But I honestly think with flagship LLM models, almost anyone with enough determination and trial and error could get an LLM to create them a odds-maker level projection model too, without needing to know how it all works statistically in the background. And that's the scary part. Do not let this fool you, being as good as Vegas is a losing strategy. My model said across 2023-2025 I was beating the odds-makers by 10% in specific scenarios. Naively it looked like free money. That strategy in 2026 so far would have lost you money. 

And to be clear, I'm also not saying someone can't beat the odds makers by more than needed to win long term. My own simulation suggests there is potentially some explainable variance to make up that odds makers, nor my model, captures. I tested this by resampling the drives within each game, using 1,556 FBS games from 2023–25 where the drive-by-drive scoring adds up to the final score. Pure drive-to-drive luck has a standard deviation of about 14 points. On those games the closing line misses by about 14.8 and my model by about 15.2, so the closing line captures roughly 85–90% of the predictable part of a margin and my model about 80%. The rest is predictable in principle, but nobody is capturing it. But obviously I don't know where that is. Vegas clearly doesn't. But I am saying it's really hard. The multi-billion dollar industry whose bottom line rests on this hasn't found it. Your buddy who "has a system" almost surely doesn't have it either.

Streaks fool people. Picture a bettor with no edge at all, winning exactly half the time. Over a 100-bet season, there's an 81% chance they hit a five-game winning streak at some point, and a 55% chance of six in a row. About 1 in 5 will win 55 or more and feel like a genius, and about 3 in 100 will hit 60%. Every one of them expects to lose $500 betting $110 a pick, yet 31% will be ahead after 100 bets. After 1,000 bets, only 7% will be. A hot streak isn't evidence of a system; each game is a new coin flip. My own 59% rule was a three-season hot streak from my model.

## What actually moves a line

Quarterbacks. Julian Sayin is out for Ohio State's regular season with an arm injury, and true freshman Luke Fahey starts in his place. My model makes Ohio State a 12.5-point favorite over Michigan with Fahey; with Sayin it would be 19.5. When a team's starter changes, the opening line moves only about 40% as far as the results do, and the closing line about 60%.

I tried the same thing for receivers, running backs and kickers. A star like Jeremiah Smith is worth about 3 points. The typical key receiver is worth about 0.2, and the typical lead running back close to nothing. Most of what a skill player does, the next guy does almost as well. This was somewhat surprising to me, that accounting for anyone but a QB didn't move the line much at all, and in the handful of instances over the last 4 seasons that it did, it did so incorrectly relative to how the games played out.

## Gambling is everywhere now... and I hate it

You can't watch a game anymore without FanDuel, DraftKings, BetMGM, and now Kalshi and Polymarket in your face: commercials, sponsored segments, billboards, stadium signage, ads on uniforms. In 1971 we took cigarette ads off television. Gambling now gets the prime slots and it's a public health crisis building in the shadows.

The newest wave is worse. Kalshi and Polymarket call their sports products "event contracts" under federal commodities rules, not bets, so they skip state gambling laws and reach states that never legalized sports betting. [About 90% of Kalshi's trading volume](https://www.actionnetwork.com/education/tracking-prediction-market-lawsuits) is sports. Through July 2026, Americans had already seen [232% more prediction-market ads](https://www.americangaming.org/wp-content/uploads/2026/08/2026-Sports-BettingPM-Advertising-Trends-3.pdf) than in all of 2025, and more than half of the digital sports-betting ads seen in 2026 didn't have to follow state rules, including responsible-gambling messaging. One industry estimate put 2025 spending on celebrity and athlete ambassadors at [$520 million, against under $60 million](https://sigma.world/news/3-9b-ad-push-by-us-gambling-firms-raises-questions/) on responsible-gambling messaging.

The industry will tell you traditional sportsbook TV ads are down, and they are: [TV ad volume has dropped by half since 2021](https://next.io/?p=152787). The ads didn't go away. They moved to places with fewer rules.

## It's a public health problem

Look at Australia. Australians lose more to gambling per person than anyone in the world: [A$1,635 per adult a year](https://grattan.edu.au/?p=75743), double the US (A$809) and almost three times New Zealand (A$584). Young men have led the growth in betting, and the Grattan Institute says the sheer volume of gambling advertising drives it. A 2023 parliamentary inquiry led by the late Peta Murphy recommended a [phased, tobacco-style ban](https://academic.oup.com/heapro/article/41/2/daag057/8661715) on online gambling advertising. The government took more than 1,000 days to respond, and in 2026 it [skipped the blanket ban](https://igamingbusiness.com/marketing-affiliates/australian-gov-responds-to-gambling-advertisment-report-reforms/).

The US is running the same experiment faster. Since the Supreme Court opened the door in 2018, most states have legalized sports betting. A [study in Management Science](https://pubsonline.informs.org/doi/10.1287/mnsc.2025.02515), using credit reports for about 7 million Americans, found that adding online sports betting lowered average credit scores by about 12 points and raised bankruptcies, debt collections and loan delinquencies. The same researchers estimated that [bankruptcy filings rose 25% to 30%](https://anderson-review.ucla.edu/as-states-permitted-online-sports-gambling-citizens-personal-financial-health-suffered) in states with online betting. Those are whole-state effects, not just problem gamblers.

It lands on the players too. An [NCAA study](https://www.ncaa.org/news/2025/11/18/media-center-ncaa-study-finds-over-one-third-of-di-mens-basketball-student-athletes-harassed-by-bettors) found that more than a third of Division I men's basketball players had been harassed by bettors, with high levels for FBS football players too. These are college kids.

Gambling doesn't leave tumors the way cigarettes do. It leaves bankruptcies, debt and harassed 20-year-olds. Gambling disorder is a diagnosable addiction, and we advertise it to every sports fan in the country.

It may not put nicotine into the body, but it works on the same machinery. In 2013, psychiatry's diagnostic manual moved gambling disorder into the same chapter as drug and alcohol addiction, citing evidence that they [share a common reward-system circuitry](https://psychnews.psychiatryonline.org/doi/10.1176/appi.pn.2013.4b14). Brain scans show that [a near-miss lights up the reward pathways much like a real win](https://brainfacts.org/Diseases-and-Disorders/Addiction/2015/Gambling-Addiction-and-the-Brain). Think of the parlay that misses by one leg. Dopamine is the clearest link: Parkinson's patients on dopamine-boosting drugs have [2 to 3.5 times the odds of impulse-control disorders](https://www.pennmedicine.org/news/news-releases/2010/may/compulsive-behaviors-more-comm), compulsive gambling among them.

It doesn't grow tumors that kill you, but it does kill people. A Swedish national registry study found that [people diagnosed with gambling disorder died by suicide at about 15 times the rate](https://pubmed.ncbi.nlm.nih.gov/30427214/) of the general population, with depression the strongest predictor. Much of that risk travels with depression and substance use, which often come with the disorder. The damage spreads to families through debt, lost jobs and broken relationships, and the National Council on Problem Gambling puts the [national social cost at $7 billion a year](https://www.ncpgambling.org/wp-content/uploads/2023/12/1-800-GAMBLER-Fact-Sheet.pdf).

If you or someone you know is struggling with gambling, the National Problem Gambling Helpline is [1-800-MY-RESET](https://ncpgambling.org/help-treatment/national-helpline-1-800-522-4700/) (1-800-697-3738), by call, text or chat, 24/7.

## The other side

The case for legal betting is real, and it deserves an answer:

- Legal sportsbooks pulled betting away from offshore books into regulated markets with consumer protections, and states collect the taxes.
- Most people bet small amounts for fun and never get hurt.
- Adults should be free to spend their money how they want.

You can believe all of that and still think it shouldn't be advertised during every timeout. The harm shows up across whole states, not just in a few problem gamblers, and the product is built so the typical customer loses. The proposed [SAFE Bet Act](https://www.globalpolicywatch.com/2024/09/bills-to-regulate-sports-betting-introduced-in-senate-and-house/) would ban broadcast sportsbook ads from 8 a.m. to 10 p.m. and during live games, and outlaw "no sweat" and "bonus bet" promotions. That's roughly where we landed with cigarettes, and it's a reasonable place to start in my opinion, but not the ending place.

## No sure thing

I'm not saying nobody can build a better model than the books. I'm saying that it's very, very hard, especially with public data, and that even a model as good as theirs loses money once you pay the vig. Every game carries about 15 points of noise no model can see, and a 59% backtest edge can turn into 50% or less the next season with nothing in the model changing.

There's no sure thing, no matter how strong the hint looks. The books know that. They've built a business on everyone else forgetting it.

## Explore it yourself, for fun

And if, FOR FUN, you want to browse predictions and power ratings, you can do so [here](https://nateoconnell.com/blog/cfb/#projections) on my website. You can explore posterior distributions, you can explore hypothetical matchups, you can review spreads and see how your favorite teams may do this next week. You can see how variable these predictions actually are. And you can do this with a model that's within 0.4 points of the opening lines across the whole 2026 season, and since week 9 has been level with or slightly better than both the opening and closing lines. As a statistician, I find this really fun to do and think about. But this is not gambling advice. Do not bet these lines. You will lose. This is for education and fun -- to show how variable all of this is, and how your "edge" you think you have because of whatever "system" you have almost surely doesn't exist.

## Sources

- Model data: play-by-play and schedules from cfbfastR (sportsdataverse) and CollegeFootballData. Lines: 2023–25 openers and closers are the median across books in the cfbfastR betting data; 2026 lines are the median of DraftKings and Bovada from CollegeFootballData. Accuracy figures are from weekly refits using only earlier games. The noise-floor test resampled drives within 1,556 FBS-vs-FBS games from 2023–25; the streak figures are exact binomial probabilities and simulations of a bettor winning 50% of 100 or 1,000 bets at −110.
- [Grattan Institute, A better bet: How Australia should prevent gambling harm](https://grattan.edu.au/?p=75743)
- [Health Promotion International, The 'Murphy Report': a blueprint for preventing online gambling harms](https://academic.oup.com/heapro/article/41/2/daag057/8661715)
- [iGaming Business, Australian government responds to the Murphy Report](https://igamingbusiness.com/marketing-affiliates/australian-gov-responds-to-gambling-advertisment-report-reforms/)
- [Management Science, The Financial Consequences of Legalized Sports Gambling](https://pubsonline.informs.org/doi/10.1287/mnsc.2025.02515)
- [UCLA Anderson Review, As states permitted online sports gambling, citizens' personal financial health suffered](https://anderson-review.ucla.edu/as-states-permitted-online-sports-gambling-citizens-personal-financial-health-suffered)
- [NCAA, Study finds over one-third of DI men's basketball student-athletes harassed by bettors](https://www.ncaa.org/news/2025/11/18/media-center-ncaa-study-finds-over-one-third-of-di-mens-basketball-student-athletes-harassed-by-bettors)
- [American Gaming Association, 2026 sports betting and prediction market advertising trends](https://www.americangaming.org/wp-content/uploads/2026/08/2026-Sports-BettingPM-Advertising-Trends-3.pdf)
- [next.io, sportsbook advertising in 2025 (AGA-commissioned study)](https://next.io/?p=152787)
- [Action Network, Tracking prediction market lawsuits](https://www.actionnetwork.com/education/tracking-prediction-market-lawsuits)
- [SIGMA, US gambling firms' $3.9B ad spend](https://sigma.world/news/3-9b-ad-push-by-us-gambling-firms-raises-questions/)
- [Global Policy Watch, SAFE Bet Act introduced](https://www.globalpolicywatch.com/2024/09/bills-to-regulate-sports-betting-introduced-in-senate-and-house/) and [Safety+Health on its promotion limits](https://www.safetyandhealthmagazine.com/?p=10604)
- [Bleacher Report, Julian Sayin injury update](https://bleacherreport.com/articles/25529602-julian-sayin-injury-update-ohio-state-hc-ryan-day-provides-latest-return-timeline-star-qb)
- [Psychiatric News, Gambling Disorder to Be Included in Addictions Chapter (DSM-5)](https://psychnews.psychiatryonline.org/doi/10.1176/appi.pn.2013.4b14)
- [BrainFacts.org, Gambling Addiction and the Brain](https://brainfacts.org/Diseases-and-Disorders/Addiction/2015/Gambling-Addiction-and-the-Brain)
- [Penn Medicine, Compulsive behaviors more common with Parkinson's dopamine agonists (DOMINION study)](https://www.pennmedicine.org/news/news-releases/2010/may/compulsive-behaviors-more-comm)
- [Karlsson and Håkansson, Gambling disorder, increased mortality, suicidality, and associated comorbidity, Journal of Behavioral Addictions (2018)](https://pubmed.ncbi.nlm.nih.gov/30427214/)
- [National Council on Problem Gambling, helpline fact sheet](https://www.ncpgambling.org/wp-content/uploads/2023/12/1-800-GAMBLER-Fact-Sheet.pdf) and [National Problem Gambling Helpline](https://ncpgambling.org/help-treatment/national-helpline-1-800-522-4700/)
