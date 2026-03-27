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
	public class TFG3003C1_Webhook : Strategy
	{
		private EMA emaFast;
		private EMA emaSlow;
		private ADX adxInd;
		private int entryBar = 0;
		private int lastExitBar = 0;

		private const string WEBHOOK_URL = "http://34.59.166.143:8088/ninja/trade";
		private const string SECRET = "NT_SYNC_2026";

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description = "TF-G3-003-C1 — Trend Following LONG ONLY on NQ 1H (with Webhook)";
				Name = "TFG3003C1_Webhook";
				Calculate = Calculate.OnBarClose;
				EntriesPerDirection = 1;
				EntryHandling = EntryHandling.AllEntries;
				IsExitOnSessionCloseStrategy = false;
				IsFillLimitOnTouch = false;
				MaximumBarsLookBack = MaximumBarsLookBack.TwoHundredFiftySix;
				OrderFillResolution = OrderFillResolution.Standard;
				Slippage = 2;
				StartBehavior = StartBehavior.WaitUntilFlat;
				TimeInForce = TimeInForce.Gtc;
				TraceOrders = false;
				RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
				StopTargetHandling = StopTargetHandling.PerEntryExecution;
				BarsRequiredToTrade = 60;

				FastEmaPeriod = 16;
				SlowEmaPeriod = 55;
				AdxThreshold = 15;
				MaxHoldBars = 12;
				CooldownBars = 3;
			}
			else if (State == State.DataLoaded)
			{
				emaFast = EMA(Close, FastEmaPeriod);
				emaSlow = EMA(Close, SlowEmaPeriod);
				adxInd = ADX(Close, 14);

				AddChartIndicator(emaFast);
				AddChartIndicator(emaSlow);
			}
		}

		protected override void OnBarUpdate()
		{
			if (CurrentBar < BarsRequiredToTrade)
				return;

			double fastVal = emaFast[0];
			double slowVal = emaSlow[0];
			double adxVal = adxInd[0];

			bool trendUp = fastVal > slowVal && adxVal > AdxThreshold && Close[0] > fastVal;

			int barsHeld = Position.MarketPosition == MarketPosition.Long ? CurrentBar - entryBar : 0;
			int barsSinceExit = CurrentBar - lastExitBar;
			bool cooldownActive = barsSinceExit < CooldownBars;
			bool maxHoldExit = MaxHoldBars > 0 && barsHeld >= MaxHoldBars;

			if (Position.MarketPosition == MarketPosition.Long)
			{
				if (fastVal < slowVal || Close[0] < slowVal || maxHoldExit)
				{
					ExitLong("TrendExit", "LongEntry");
					lastExitBar = CurrentBar;
				}
			}

			if (Position.MarketPosition == MarketPosition.Flat && !cooldownActive)
			{
				if (trendUp)
				{
					EnterLong("LongEntry");
					entryBar = CurrentBar;
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
					"{{\"secret\":\"{0}\",\"strategy\":\"{1}\",\"instrument\":\"{2}\",\"direction\":\"{3}\",\"entry_price\":{4},\"exit_price\":{5},\"quantity\":{6},\"pnl\":0,\"action\":\"{7}\",\"timestamp\":\"{8}\",\"order_id\":\"{9}\"}}",
					SECRET, "TFG3003C1", Instrument.FullName, direction,
					price.ToString("F2"), action == "exit" ? price.ToString("F2") : "0",
					quantity, action, DateTime.UtcNow.ToString("o"), orderId);

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
		[Display(Name = "Fast EMA Period", Order = 1, GroupName = "Parameters")]
		public int FastEmaPeriod { get; set; }

		[NinjaScriptProperty]
		[Range(1, int.MaxValue)]
		[Display(Name = "Slow EMA Period", Order = 2, GroupName = "Parameters")]
		public int SlowEmaPeriod { get; set; }

		[NinjaScriptProperty]
		[Range(1, 100)]
		[Display(Name = "ADX Threshold", Order = 3, GroupName = "Parameters")]
		public int AdxThreshold { get; set; }

		[NinjaScriptProperty]
		[Range(1, int.MaxValue)]
		[Display(Name = "Max Hold Bars", Order = 4, GroupName = "Parameters")]
		public int MaxHoldBars { get; set; }

		[NinjaScriptProperty]
		[Range(0, int.MaxValue)]
		[Display(Name = "Cooldown Bars After Exit", Order = 5, GroupName = "Parameters")]
		public int CooldownBars { get; set; }
		#endregion
	}
}
