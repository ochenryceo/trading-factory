#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Xml.Serialization;
using NinjaTrader.Cbi;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Chart;
using NinjaTrader.Gui.SuperDom;
using NinjaTrader.Gui.Tools;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.Core.FloatingPoint;
using NinjaTrader.NinjaScript.Indicators;
using NinjaTrader.NinjaScript.DrawingTools;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
	public class LockedProductionV1 : Strategy
	{
		private RSI rsi;
		private Bollinger bb;
		private SMA volSma;

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description = "LOCKED_PRODUCTION_V1 - RSI/BB Mean Reversion on NQ Daily";
				Name = "LockedProductionV1";
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

			// Entry: RSI oversold + price at/below BB lower + volume confirmation
			bool entrySignal = currentRsi < RsiThreshold
				&& Close[0] <= lowerBand
				&& Volume[0] > avgVol * VolMultiplier;

			// Exit: RSI recovers or signal goes flat
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
