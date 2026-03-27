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
	public class NRG3004C1 : Strategy
	{
		private ATR atrInd;
		private SMA atrAvg;
		private SMA volAvg;
		private Bollinger bb;
		private Series<double> atrSeries;
		private Series<double> bbWidthSeries;
		private int entryBar = 0;

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description = "NR-G3-004-C1 - Pre-Event Compression Breakout on NQ 1H";
				Name = "NRG3004C1";
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
				BarsRequiredToTrade = 252;

				AtrPeriod = 14;
				AtrAvgPeriod = 20;
				AtrBurstMult = 1.3;
				VolAvgPeriod = 20;
				VolMult = 1.5;
				MomPeriod = 3;
				MinHoldBars = 3;
				MaxHoldBars = 20;
				BbPeriod = 20;
				BbStdDev = 2.0;
				BbPctMax = 15.0;
				BbRankLen = 252;
				UseBbFilter = true;
			}
			else if (State == State.DataLoaded)
			{
				atrInd = ATR(Close, AtrPeriod);
				atrAvg = SMA(atrInd, AtrAvgPeriod);
				volAvg = SMA(Volume, VolAvgPeriod);
				bb = Bollinger(Close, BbStdDev, BbPeriod);
				atrSeries = new Series<double>(this);
				bbWidthSeries = new Series<double>(this);
			}
		}

		protected override void OnBarUpdate()
		{
			if (CurrentBar < BarsRequiredToTrade)
				return;

			// ATR burst detection
			double atrVal = atrInd[0];
			double atrAvgVal = atrAvg[0];
			bool atrBurst = atrVal > atrAvgVal * AtrBurstMult;

			// Volume spike detection
			double volAvgVal = volAvg[0];
			bool volSpike = Volume[0] > volAvgVal * VolMult;

			// Combined burst
			bool burst = atrBurst && volSpike;

			// BB compression filter
			double bbWidth = (bb.Upper[0] - bb.Lower[0]) / bb.Middle[0];
			bbWidthSeries[0] = bbWidth;

			// Compute percentile rank of BB width
			bool compression = false;
			if (UseBbFilter && CurrentBar >= BbRankLen)
			{
				int countBelow = 0;
				for (int i = 0; i < BbRankLen; i++)
				{
					if (bbWidthSeries[i] <= bbWidth)
						countBelow++;
				}
				double rank = (double)countBelow / BbRankLen * 100.0;
				compression = rank <= BbPctMax;
			}

			// Merge triggers
			bool trigger = burst || (UseBbFilter && compression && Volume[0] > volAvgVal * Math.Max(1.0, VolMult * 0.6));

			// Momentum
			double mom = Close[0] - Close[MomPeriod];

			// Entry signals
			bool longSignal = trigger && mom > 0;
			bool shortSignal = trigger && mom < 0;

			// Bars in trade
			int barsHeld = 0;
			if (Position.MarketPosition != MarketPosition.Flat)
				barsHeld = CurrentBar - entryBar;

			bool canExit = barsHeld >= MinHoldBars;
			bool maxHoldExit = MaxHoldBars > 0 && barsHeld >= MaxHoldBars;

			// Entry
			if (Position.MarketPosition == MarketPosition.Flat || Position.MarketPosition == MarketPosition.Short)
			{
				if (longSignal)
				{
					if (Position.MarketPosition == MarketPosition.Short)
						ExitShort("FlipToLong", "ShortEntry");
					EnterLong("LongEntry");
					entryBar = CurrentBar;
				}
			}

			if (Position.MarketPosition == MarketPosition.Flat || Position.MarketPosition == MarketPosition.Long)
			{
				if (shortSignal)
				{
					if (Position.MarketPosition == MarketPosition.Long)
						ExitLong("FlipToShort", "LongEntry");
					EnterShort("ShortEntry");
					entryBar = CurrentBar;
				}
			}

			// Exit on momentum reversal (after min hold)
			if (Position.MarketPosition == MarketPosition.Long && canExit)
			{
				if (mom <= 0 || maxHoldExit)
					ExitLong("MomExit", "LongEntry");
			}

			if (Position.MarketPosition == MarketPosition.Short && canExit)
			{
				if (mom >= 0 || maxHoldExit)
					ExitShort("MomExit", "ShortEntry");
			}
		}

		#region Properties
		[NinjaScriptProperty]
		[Range(1, int.MaxValue)]
		[Display(Name = "ATR Period", Order = 1, GroupName = "Parameters")]
		public int AtrPeriod { get; set; }

		[NinjaScriptProperty]
		[Range(1, int.MaxValue)]
		[Display(Name = "ATR Avg Period", Order = 2, GroupName = "Parameters")]
		public int AtrAvgPeriod { get; set; }

		[NinjaScriptProperty]
		[Range(0.1, double.MaxValue)]
		[Display(Name = "ATR Burst Multiplier", Order = 3, GroupName = "Parameters")]
		public double AtrBurstMult { get; set; }

		[NinjaScriptProperty]
		[Range(1, int.MaxValue)]
		[Display(Name = "Vol Avg Period", Order = 4, GroupName = "Parameters")]
		public int VolAvgPeriod { get; set; }

		[NinjaScriptProperty]
		[Range(0.1, double.MaxValue)]
		[Display(Name = "Volume Multiplier", Order = 5, GroupName = "Parameters")]
		public double VolMult { get; set; }

		[NinjaScriptProperty]
		[Range(1, int.MaxValue)]
		[Display(Name = "Momentum Period", Order = 6, GroupName = "Parameters")]
		public int MomPeriod { get; set; }

		[NinjaScriptProperty]
		[Range(1, int.MaxValue)]
		[Display(Name = "Min Hold Bars", Order = 7, GroupName = "Parameters")]
		public int MinHoldBars { get; set; }

		[NinjaScriptProperty]
		[Range(0, int.MaxValue)]
		[Display(Name = "Max Hold Bars", Order = 8, GroupName = "Parameters")]
		public int MaxHoldBars { get; set; }

		[NinjaScriptProperty]
		[Range(1, int.MaxValue)]
		[Display(Name = "BB Period", Order = 9, GroupName = "Parameters")]
		public int BbPeriod { get; set; }

		[NinjaScriptProperty]
		[Range(0.1, double.MaxValue)]
		[Display(Name = "BB Std Dev", Order = 10, GroupName = "Parameters")]
		public double BbStdDev { get; set; }

		[NinjaScriptProperty]
		[Range(0.1, 100.0)]
		[Display(Name = "BB Pct Max", Order = 11, GroupName = "Parameters")]
		public double BbPctMax { get; set; }

		[NinjaScriptProperty]
		[Range(1, int.MaxValue)]
		[Display(Name = "BB Rank Length", Order = 12, GroupName = "Parameters")]
		public int BbRankLen { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Use BB Filter", Order = 13, GroupName = "Parameters")]
		public bool UseBbFilter { get; set; }
		#endregion
	}
}
