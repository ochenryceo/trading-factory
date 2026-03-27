#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Linq;
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
    public class TFG3003C1 : Strategy
    {
        private EMA emaFast;
        private EMA emaSlow;
        private ADX adxInd;
        private int entryBar = 0;
        private int lastExitBar = 0;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "TF-G3-003-C1 — Trend Following on NQ 1H (Conditional Candidate)";
                Name = "TFG3003C1";
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
            bool trendDown = fastVal < slowVal && adxVal > AdxThreshold && Close[0] < fastVal;

            int barsHeld = Position.MarketPosition != MarketPosition.Flat ? CurrentBar - entryBar : 0;
            int barsSinceExit = CurrentBar - lastExitBar;
            bool cooldownActive = barsSinceExit < CooldownBars;
            bool maxHoldExit = MaxHoldBars > 0 && barsHeld >= MaxHoldBars;

            // Exit: trend reversal or max hold
            if (Position.MarketPosition == MarketPosition.Long)
            {
                if (fastVal < slowVal || Close[0] < slowVal || maxHoldExit)
                {
                    ExitLong("TrendExit", "LongEntry");
                    lastExitBar = CurrentBar;
                }
            }
            else if (Position.MarketPosition == MarketPosition.Short)
            {
                if (fastVal > slowVal || Close[0] > slowVal || maxHoldExit)
                {
                    ExitShort("TrendExit", "ShortEntry");
                    lastExitBar = CurrentBar;
                }
            }

            // Entry: only when flat + cooldown expired
            if (Position.MarketPosition == MarketPosition.Flat && !cooldownActive)
            {
                if (trendUp)
                {
                    EnterLong("LongEntry");
                    entryBar = CurrentBar;
                }
                else if (trendDown)
                {
                    EnterShort("ShortEntry");
                    entryBar = CurrentBar;
                }
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
