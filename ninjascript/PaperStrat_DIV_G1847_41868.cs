#region Using declarations
using System;
using System.IO;
using System.Net;
using System.Text;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.Core.FloatingPoint;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
	/// <summary>
	/// DIV-G1847-41868 — News/Mean Reversion | NQ | 1H
	/// Entry: RSI(8) < 45 AND Close < BB_Lower(16,2)
	/// Exit:  RSI(8) > 50 OR Close > BB_Mid(16)
	/// Exit Engine: 5% profit trigger → trailing stop (25% giveback)
	/// Note: "news" style uses mean reversion entry logic per backtester
	/// </summary>
	public class PaperStrat_DIV_G1847_41868 : Strategy
	{
		private RSI rsi;
		private Bollinger bb;

		private double entryPrice = 0;
		private double peakProfit = 0;
		private bool trailingActive = false;

		private const string WEBHOOK_URL = "http://34.59.166.143:8088/ninja/trade";
		private const string SECRET = "NT_SYNC_2026";
		private const string STRAT_NAME = "DIV-G1847-41868";

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description = "DIV-G1847-41868 — News/MR NQ 1H (Paper)";
				Name = "PaperStrat_DIV_G1847_41868";
				Calculate = Calculate.OnBarClose;
				EntriesPerDirection = 1;
				EntryHandling = EntryHandling.AllEntries;
				IsExitOnSessionCloseStrategy = false;
				MaximumBarsLookBack = MaximumBarsLookBack.TwoHundredFiftySix;
				OrderFillResolution = OrderFillResolution.Standard;
				Slippage = 2;
				StartBehavior = StartBehavior.WaitUntilFlat;
				TimeInForce = TimeInForce.Gtc;
				RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
				BarsRequiredToTrade = 20;

				RsiPeriod = 8;
				RsiEntryThreshold = 45;
				RsiExitThreshold = 50;
				BbPeriod = 16;
				BbStdDev = 2.0;
				ProfitTargetPct = 0.05;
				TrailGivebackPct = 0.25;
			}
			else if (State == State.DataLoaded)
			{
				rsi = RSI(Close, RsiPeriod, 1);
				bb = Bollinger(Close, BbStdDev, BbPeriod);

				AddChartIndicator(rsi);
				AddChartIndicator(bb);
			}
		}

		protected override void OnBarUpdate()
		{
			if (CurrentBar < BarsRequiredToTrade)
				return;

			if (Position.MarketPosition == MarketPosition.Flat)
			{
				// News style entry: RSI < threshold AND price below lower BB
				bool entrySignal = rsi[0] < RsiEntryThreshold
					&& Close[0] <= bb.Lower[0];

				if (entrySignal)
				{
					EnterLong(1, "LongEntry");
					entryPrice = Close[0];
					peakProfit = 0;
					trailingActive = false;
				}
			}
			else if (Position.MarketPosition == MarketPosition.Long)
			{
				bool exitSignal = rsi[0] > RsiExitThreshold
					|| Close[0] > bb.Middle[0];

				double currentProfit = (Close[0] - entryPrice) / entryPrice;
				if (currentProfit > peakProfit)
					peakProfit = currentProfit;

				if (!trailingActive && currentProfit >= ProfitTargetPct)
					trailingActive = true;

				bool trailingExit = false;
				if (trailingActive && peakProfit > 0)
				{
					double giveback = (peakProfit - currentProfit) / peakProfit;
					if (giveback >= TrailGivebackPct)
						trailingExit = true;
				}

				if (exitSignal || trailingExit)
				{
					string reason = trailingExit ? "TrailingStop" : "SignalExit";
					ExitLong(reason, "LongEntry");
				}
			}
		}

		protected override void OnExecutionUpdate(Execution execution, string executionId, double price, int quantity, MarketPosition marketPosition, string orderId, DateTime time)
		{
			if (execution.Order == null || execution.Order.OrderState != OrderState.Filled)
				return;

			try
			{
				string direction = marketPosition == MarketPosition.Long ? "Long" :
								   marketPosition == MarketPosition.Short ? "Short" : "Flat";
				string action = marketPosition == MarketPosition.Flat ? "exit" : "entry";

				string json = string.Format(
					"{{\"secret\":\"{0}\",\"strategy\":\"{1}\",\"instrument\":\"{2}\",\"direction\":\"{3}\",\"entry_price\":{4},\"exit_price\":{5},\"quantity\":{6},\"pnl\":{7},\"action\":\"{8}\",\"timestamp\":\"{9}\",\"order_id\":\"{10}\"}}",
					SECRET, STRAT_NAME, Instrument.FullName, direction,
					price.ToString("F2"), action == "exit" ? price.ToString("F2") : "0",
					quantity, Position.GetUnrealizedProfitLoss(PerformanceUnit.Currency).ToString("F2"),
					action, DateTime.UtcNow.ToString("o"), orderId);

				SendWebhook(json);
			}
			catch (Exception ex)
			{
				Print("Webhook error: " + ex.Message);
			}
		}

		private void SendWebhook(string json)
		{
			try
			{
				var request = (HttpWebRequest)WebRequest.Create(WEBHOOK_URL);
				request.Method = "POST";
				request.ContentType = "application/json";
				request.Timeout = 5000;
				byte[] bytes = Encoding.UTF8.GetBytes(json);
				request.ContentLength = bytes.Length;

				using (var stream = request.GetRequestStream())
					stream.Write(bytes, 0, bytes.Length);

				using (var response = (HttpWebResponse)request.GetResponse())
					Print(STRAT_NAME + " webhook OK: HTTP " + (int)response.StatusCode);
			}
			catch (Exception ex)
			{
				Print(STRAT_NAME + " webhook failed: " + ex.Message);
			}
		}

		#region Properties
		[NinjaScriptProperty]
		[Range(1, 100)]
		[Display(Name = "RSI Period", Order = 1, GroupName = "Parameters")]
		public int RsiPeriod { get; set; }

		[NinjaScriptProperty]
		[Range(1, 100)]
		[Display(Name = "RSI Entry Threshold", Order = 2, GroupName = "Parameters")]
		public int RsiEntryThreshold { get; set; }

		[NinjaScriptProperty]
		[Range(1, 100)]
		[Display(Name = "RSI Exit Threshold", Order = 3, GroupName = "Parameters")]
		public int RsiExitThreshold { get; set; }

		[NinjaScriptProperty]
		[Range(1, 100)]
		[Display(Name = "BB Period", Order = 4, GroupName = "Parameters")]
		public int BbPeriod { get; set; }

		[NinjaScriptProperty]
		[Range(0.1, 10)]
		[Display(Name = "BB Std Dev", Order = 5, GroupName = "Parameters")]
		public double BbStdDev { get; set; }

		[NinjaScriptProperty]
		[Range(0.01, 1.0)]
		[Display(Name = "Profit Target %", Order = 6, GroupName = "Exit Engine")]
		public double ProfitTargetPct { get; set; }

		[NinjaScriptProperty]
		[Range(0.01, 1.0)]
		[Display(Name = "Trail Giveback %", Order = 7, GroupName = "Exit Engine")]
		public double TrailGivebackPct { get; set; }
		#endregion
	}
}
