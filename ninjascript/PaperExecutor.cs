#region Using declarations
using System;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
	/// <summary>
	/// PaperExecutor — Dumb Execution Engine
	/// Each instance filters by StrategyFilter — only executes signals matching its assigned strategy.
	/// Deploy one per chart, one per strategy.
	/// </summary>
	public class PaperExecutor : Strategy
	{
		private const string SIGNAL_URL = "http://34.59.166.143:8088/signals/pending";
		private const string ACK_URL = "http://34.59.166.143:8088/signals/ack";
		private const string FILL_URL = "http://34.59.166.143:8088/ninja/trade";
		private const string SECRET = "NT_SYNC_2026";

		private DateTime lastPoll = DateTime.MinValue;

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description = "PaperExecutor — Polls for signals, executes market orders. Set StrategyFilter to assign which strategy this instance handles.";
				Name = "PaperExecutor";
				Calculate = Calculate.OnBarClose;
				EntriesPerDirection = 1;
				EntryHandling = EntryHandling.UniqueEntries;
				IsExitOnSessionCloseStrategy = false;
				MaximumBarsLookBack = MaximumBarsLookBack.TwoHundredFiftySix;
				OrderFillResolution = OrderFillResolution.Standard;
				Slippage = 2;
				StartBehavior = StartBehavior.WaitUntilFlat;
				TimeInForce = TimeInForce.Gtc;
				RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
				BarsRequiredToTrade = 1;

				PollIntervalSeconds = 10;
				StrategyFilter = "ALL";
			}
		}

		protected override void OnBarUpdate()
		{
			if (State != State.Realtime)
				return;

			if ((DateTime.Now - lastPoll).TotalSeconds < PollIntervalSeconds)
				return;

			lastPoll = DateTime.Now;
			PollForSignals();
		}

		private void PollForSignals()
		{
			try
			{
				string response = HttpGet(SIGNAL_URL + "?secret=" + SECRET);
				if (string.IsNullOrEmpty(response))
					return;

				int arrStart = response.IndexOf("[");
				int arrEnd = response.LastIndexOf("]");
				if (arrStart < 0 || arrEnd <= arrStart)
					return;

				string arrContent = response.Substring(arrStart + 1, arrEnd - arrStart - 1).Trim();
				if (string.IsNullOrEmpty(arrContent))
					return;

				string[] parts = arrContent.Split(new string[] { "},{" }, StringSplitOptions.RemoveEmptyEntries);

				foreach (string part in parts)
				{
					string clean = "{" + part.TrimStart('{').TrimEnd('}') + "}";

					string id = ExtractValue(clean, "id");
					string action = ExtractValue(clean, "action").ToUpperInvariant();
					string strategy = ExtractValue(clean, "strategy");

					if (string.IsNullOrEmpty(action) || string.IsNullOrEmpty(strategy))
						continue;

					// STRATEGY FILTER — only process signals for this instance's assigned strategy
					if (StrategyFilter != "ALL" && strategy != StrategyFilter)
						continue;

					Print(string.Format("PaperExecutor [{0}]: {1} signal for {2}", StrategyFilter, action, strategy));

					string entryName = "Exec_" + strategy;

					if (action == "BUY")
					{
						if (Position.MarketPosition == MarketPosition.Flat)
						{
							EnterLong(1, entryName);
							Print("→ LONG entered for " + strategy);
						}
					}
					else if (action == "SELL" || action == "EXIT" || action == "CLOSE" || action == "FLAT")
					{
						if (Position.MarketPosition == MarketPosition.Long)
						{
							ExitLong("Exit_" + strategy, entryName);
							Print("→ EXIT for " + strategy);
						}
					}

					// Ack the signal
					if (!string.IsNullOrEmpty(id))
					{
						string ackJson = string.Format("{{\"secret\":\"{0}\",\"signal_id\":\"{1}\"}}", SECRET, id);
						SendWebhook(ACK_URL, ackJson);
					}
				}
			}
			catch (Exception ex)
			{
				if (!ex.Message.Contains("refused"))
					Print("PaperExecutor poll error: " + ex.Message);
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
				try { pnl = Position.GetUnrealizedProfitLoss(PerformanceUnit.Currency); } catch { }

				string stratName = StrategyFilter != "ALL" ? StrategyFilter : "unknown";
				if (stratName == "unknown" && execution.Order.Name != null && execution.Order.Name.Contains("_"))
				{
					int idx = execution.Order.Name.IndexOf("_");
					if (idx >= 0 && idx + 1 < execution.Order.Name.Length)
						stratName = execution.Order.Name.Substring(idx + 1);
				}

				string json = string.Format(
					"{{\"secret\":\"{0}\",\"strategy\":\"{1}\",\"instrument\":\"{2}\",\"direction\":\"{3}\",\"entry_price\":{4},\"exit_price\":{5},\"quantity\":{6},\"pnl\":{7},\"action\":\"{8}\",\"timestamp\":\"{9}\",\"order_id\":\"{10}\"}}",
					SECRET, stratName, Instrument.FullName, direction,
					price.ToString("F2"), action == "exit" ? price.ToString("F2") : "0",
					quantity, pnl.ToString("F2"), action,
					DateTime.UtcNow.ToString("o"), orderId);

				SendWebhook(FILL_URL, json);
				Print(string.Format("PaperExecutor [{0}] fill: {1} {2} @ {3}", StrategyFilter, action, direction, price));
			}
			catch (Exception ex)
			{
				Print("PaperExecutor fill error: " + ex.Message);
			}
		}

		private string HttpGet(string url)
		{
			try
			{
				var request = (HttpWebRequest)WebRequest.Create(url);
				request.Method = "GET";
				request.Timeout = 5000;
				using (var response = (HttpWebResponse)request.GetResponse())
				using (var reader = new StreamReader(response.GetResponseStream()))
					return reader.ReadToEnd();
			}
			catch { return ""; }
		}

		private void SendWebhook(string url, string json)
		{
			try
			{
				var request = (HttpWebRequest)WebRequest.Create(url);
				request.Method = "POST";
				request.ContentType = "application/json";
				request.Timeout = 5000;
				byte[] bytes = Encoding.UTF8.GetBytes(json);
				request.ContentLength = bytes.Length;
				using (var stream = request.GetRequestStream())
					stream.Write(bytes, 0, bytes.Length);
				using (var response = (HttpWebResponse)request.GetResponse()) { }
			}
			catch { }
		}

		private string ExtractValue(string json, string key)
		{
			string search = "\"" + key + "\"";
			int idx = json.IndexOf(search);
			if (idx < 0) return "";
			int colonIdx = json.IndexOf(":", idx + search.Length);
			if (colonIdx < 0) return "";
			int valStart = colonIdx + 1;
			while (valStart < json.Length && (json[valStart] == ' ' || json[valStart] == '"'))
				valStart++;
			int valEnd = valStart;
			while (valEnd < json.Length && json[valEnd] != '"' && json[valEnd] != ',' && json[valEnd] != '}')
				valEnd++;
			return valEnd > valStart ? json.Substring(valStart, valEnd - valStart).Trim() : "";
		}

		#region Properties
		[NinjaScriptProperty]
		[Range(1, 300)]
		[Display(Name = "Poll Interval (seconds)", Order = 1, GroupName = "Settings")]
		public int PollIntervalSeconds { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Strategy Filter", Description = "Strategy name this executor handles. Set to ALL to handle any signal.", Order = 2, GroupName = "Settings")]
		public string StrategyFilter { get; set; }
		#endregion
	}
}
