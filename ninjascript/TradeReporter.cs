#region Using declarations
using System;
using System.IO;
using System.Net;
using System.Text;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
	public class TradeReporter : Strategy
	{
		private MarketPosition lastPosition = MarketPosition.Flat;

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description = "Reports trades to the Trading Factory webhook receiver";
				Name = "TradeReporter";
				Calculate = Calculate.OnBarClose;
				IsExitOnSessionCloseStrategy = false;
				IsFillLimitOnTouch = false;
				StartBehavior = StartBehavior.WaitUntilFlat;
				RealtimeErrorHandling = RealtimeErrorHandling.IgnoreAllErrors;

				WebhookUrl = "http://34.59.166.143:8088/ninja/trade";
				Secret = "NT_SYNC_2026";
				StrategyName = "LockedProductionV1";
			}
		}

		protected override void OnBarUpdate() { }

		protected override void OnExecutionUpdate(Execution execution, string executionId, double price, int quantity, MarketPosition marketPosition, string orderId, DateTime time)
		{
			if (execution.Order == null || execution.Order.OrderState != OrderState.Filled)
				return;

			try
			{
				string direction = marketPosition == MarketPosition.Long ? "Long" :
								   marketPosition == MarketPosition.Short ? "Short" : "Flat";
				string action = marketPosition == MarketPosition.Flat ? "exit" : "entry";

				string json = "{"
					+ "\"secret\":\"" + Secret + "\","
					+ "\"strategy\":\"" + StrategyName + "\","
					+ "\"instrument\":\"" + Instrument.FullName + "\","
					+ "\"direction\":\"" + direction + "\","
					+ "\"entry_price\":" + price.ToString("F2") + ","
					+ "\"exit_price\":" + (action == "exit" ? price.ToString("F2") : "0") + ","
					+ "\"quantity\":" + quantity + ","
					+ "\"pnl\":0,"
					+ "\"action\":\"" + action + "\","
					+ "\"timestamp\":\"" + DateTime.UtcNow.ToString("o") + "\","
					+ "\"order_id\":\"" + orderId + "\""
					+ "}";

				SendWebhook(json);
			}
			catch (Exception ex)
			{
				Print("TradeReporter error: " + ex.Message);
			}
		}

		protected override void OnPositionUpdate(Position position, double averagePrice, int quantity, MarketPosition marketPosition)
		{
			// Log position changes for debugging
			Print("TradeReporter [" + StrategyName + "] Position: " + marketPosition + " qty=" + quantity + " @ " + averagePrice);
		}

		private void SendWebhook(string json)
		{
			try
			{
				var request = (HttpWebRequest)WebRequest.Create(WebhookUrl);
				request.Method = "POST";
				request.ContentType = "application/json";
				request.Timeout = 5000;
				byte[] bytes = Encoding.UTF8.GetBytes(json);
				request.ContentLength = bytes.Length;

				using (var stream = request.GetRequestStream())
					stream.Write(bytes, 0, bytes.Length);

				using (var response = (HttpWebResponse)request.GetResponse())
					Print("TradeReporter [" + StrategyName + "] Webhook OK: HTTP " + (int)response.StatusCode);
			}
			catch (Exception ex)
			{
				Print("TradeReporter [" + StrategyName + "] Webhook FAILED: " + ex.Message);
			}
		}

		#region Properties
		[NinjaScriptProperty]
		[Display(Name = "Webhook URL", Order = 1, GroupName = "Connection")]
		public string WebhookUrl { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Secret", Order = 2, GroupName = "Connection")]
		public string Secret { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Strategy Name", Order = 3, GroupName = "Connection")]
		public string StrategyName { get; set; }
		#endregion
	}
}
