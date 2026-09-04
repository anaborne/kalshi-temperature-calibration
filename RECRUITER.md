# In plain English

Kalshi is an exchange where people trade contracts on the daily high temperature
in American cities. The weather readings that settle those contracts are public
and free all day, so the question was whether the exchange's prices lag the
readings by enough to trade against. I wrote the test down before I ran it,
pulled 60,906 settled contracts across 21 cities and 6.8 million hourly weather
readings, and built a model that predicts where the day's high will land. Over
235,145 hours in twelve cities, the exchange's own price was the better
forecast, scoring 0.0772 on a standard forecast error measure against my model's
0.1739, where lower is better. I then ran the trading rule once on nine cities I
had held back, and it lost money in all four seasons and all three trade types,
8.75 cents per contract over 19,348 trades, or $27,039 on paper. The repository
holds the plan, the code, the run logs, and the errors later found in my own
work.
