#region Using declarations
using System;
using System.IO;
using System.Net;
using System.Text;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using System.Windows;
using System.Windows.Media;
using NinjaTrader.Cbi;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Chart;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.Core.FloatingPoint;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
	public class LockedProductionV1_Webhook : Strategy
	{
		private RSI rsi;
		private Bollinger bb;
		private SMA volSma;

		private const string WEBHOOK_URL = "http://34.59.166.143:8088/ninja/trade";
		private const string SECRET = "NT_SYNC_2026";

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description = "LOCKED_PRODUCTION_V1 - RSI/BB Mean Reversion on NQ Daily (with Webhook)";
				Name = "LockedProductionV1_Webhook";
				Calculate = Calculate.OnBarClose;
				EntriesPerDirection = 1;
				EntryHandling = EntryHandling.AllEntries;
				IsExitOnSessionCloseStrategy = false;
				ExitOnSessionCloseSeconds = 30;
				IsFillLimitOnTouch = false;
				MaximumBarsLookBack = MaximumBarsLookBack.TwoHundredFiftySix;
				OrderFillResolution = OrderFillResolution.Standard;
				Slippage = 2;
				StartBehavior = StartBehavior.WaitUntilFlat;
				TimeInForce = TimeInForce.Gtc;
				TraceOrders = false;
				RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
				StopTargetHandling = StopTargetHandling.PerEntryExecution;
				BarsRequiredToTrade = 20;

				RsiPeriod = 7;
				RsiThreshold = 30;
				BbPeriod = 20;
				BbStdDev = 2.0;
				VolMultiplier = 1.47;
				VolPeriod = 20;
			}
			else if (State == State.DataLoaded)
			{
				rsi = RSI(Close, RsiPeriod, 1);
				bb = Bollinger(Close, BbStdDev, BbPeriod);
				volSma = SMA(Volume, VolPeriod);

				AddChartIndicator(rsi);
				AddChartIndicator(bb);
			}
		}

		protected override void OnBarUpdate()
		{
			if (CurrentBar < BarsRequiredToTrade)
				return;

			double currentRsi = rsi[0];
			double lowerBand = bb.Lower[0];
			double avgVol = volSma[0];

			bool entrySignal = currentRsi < RsiThreshold
				&& Close[0] <= lowerBand
				&& Volume[0] > avgVol * VolMultiplier;

			bool exitSignal = currentRsi > 60;

			if (Position.MarketPosition == MarketPosition.Flat && entrySignal)
			{
				EnterLong("LongEntry");
			}

			if (Position.MarketPosition == MarketPosition.Long && exitSignal)
			{
				ExitLong("ExitSignal", "LongEntry");
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
				double pnl = 0;

				string json = string.Format(
					"{{\"secret\":\"{0}\",\"strategy\":\"{1}\",\"instrument\":\"{2}\",\"direction\":\"{3}\",\"entry_price\":{4},\"exit_price\":{5},\"quantity\":{6},\"pnl\":{7},\"action\":\"{8}\",\"timestamp\":\"{9}\",\"order_id\":\"{10}\"}}",
					SECRET, "LockedProductionV1", Instrument.FullName, direction,
					price.ToString("F2"), action == "exit" ? price.ToString("F2") : "0",
					quantity, pnl.ToString("F2"), action,
					DateTime.UtcNow.ToString("o"), orderId);

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
					Print("Webhook OK: HTTP " + (int)response.StatusCode);
			}
			catch (Exception ex)
			{
				Print("Webhook failed: " + ex.Message);
			}
		}

		#region Properties
		[NinjaScriptProperty]
		[Range(1, int.MaxValue)]
		[Display(Name = "RSI Period", Order = 1, GroupName = "Parameters")]
		public int RsiPeriod { get; set; }

		[NinjaScriptProperty]
		[Range(1, 100)]
		[Display(Name = "RSI Threshold", Order = 2, GroupName = "Parameters")]
		public int RsiThreshold { get; set; }

		[NinjaScriptProperty]
		[Range(1, int.MaxValue)]
		[Display(Name = "BB Period", Order = 3, GroupName = "Parameters")]
		public int BbPeriod { get; set; }

		[NinjaScriptProperty]
		[Range(0.1, double.MaxValue)]
		[Display(Name = "BB Std Dev", Order = 4, GroupName = "Parameters")]
		public double BbStdDev { get; set; }

		[NinjaScriptProperty]
		[Range(0.1, double.MaxValue)]
		[Display(Name = "Volume Multiplier", Order = 5, GroupName = "Parameters")]
		public double VolMultiplier { get; set; }

		[NinjaScriptProperty]
		[Range(1, int.MaxValue)]
		[Display(Name = "Volume Period", Order = 6, GroupName = "Parameters")]
		public int VolPeriod { get; set; }
		#endregion
	}
}
