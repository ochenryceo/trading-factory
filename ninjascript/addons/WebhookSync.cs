#region Using declarations
using System;
using System.IO;
using System.Net;
using System.Text;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
	/// <summary>
	/// Mixin helper — call from any strategy's OnExecutionUpdate to POST trades to the factory webhook.
	/// 
	/// Usage in your strategy:
	///   1. Add: private WebhookSync webhook;
	///   2. In OnStateChange (State.DataLoaded): webhook = new WebhookSync("StrategyName", "NQ", Log);
	///   3. In OnExecutionUpdate: webhook.OnTrade(execution, Position);
	/// </summary>
	public class WebhookSync
	{
		private readonly string _strategyName;
		private readonly string _instrument;
		private readonly Action<string> _log;
		private const string WEBHOOK_URL = "http://34.59.166.143:8088/ninja/trade";
		private const string SECRET = "NT_SYNC_2026";

		public WebhookSync(string strategyName, string instrument, Action<string> log)
		{
			_strategyName = strategyName;
			_instrument = instrument;
			_log = log;
		}

		public void OnTrade(Execution execution, Position position)
		{
			if (execution.Order == null || execution.Order.OrderState != OrderState.Filled)
				return;

			try
			{
				string direction = position.MarketPosition == MarketPosition.Long ? "Long" : 
								   position.MarketPosition == MarketPosition.Short ? "Short" : "Flat";
				string action = position.MarketPosition == MarketPosition.Flat ? "exit" : "entry";
				double pnl = position.MarketPosition == MarketPosition.Flat ? position.GetUnrealizedProfitLoss(PerformanceUnit.Currency) : 0;

				string json = string.Format(
					"{{\"secret\":\"{0}\",\"strategy\":\"{1}\",\"instrument\":\"{2}\",\"direction\":\"{3}\",\"entry_price\":{4},\"exit_price\":{5},\"quantity\":{6},\"pnl\":{7},\"action\":\"{8}\",\"timestamp\":\"{9}\",\"order_id\":\"{10}\"}}",
					SECRET,
					_strategyName,
					_instrument,
					direction,
					execution.Price.ToString("F2"),
					action == "exit" ? execution.Price.ToString("F2") : "0",
					execution.Quantity,
					pnl.ToString("F2"),
					action,
					DateTime.UtcNow.ToString("o"),
					execution.Order.OrderId
				);

				var request = (HttpWebRequest)WebRequest.Create(WEBHOOK_URL);
				request.Method = "POST";
				request.ContentType = "application/json";
				request.Timeout = 5000;
				byte[] bytes = Encoding.UTF8.GetBytes(json);
				request.ContentLength = bytes.Length;

				using (var stream = request.GetRequestStream())
				{
					stream.Write(bytes, 0, bytes.Length);
				}

				using (var response = (HttpWebResponse)request.GetResponse())
				{
					_log?.Invoke($"Webhook sent: {action} {direction} @ {execution.Price} — HTTP {(int)response.StatusCode}");
				}
			}
			catch (Exception ex)
			{
				_log?.Invoke($"Webhook error: {ex.Message}");
			}
		}
	}
}
