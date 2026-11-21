//+------------------------------------------------------------------+
//| Alhaidani Bridge Receiver (SAFE MONITOR - NO ORDER EXECUTION)     |
//| First stage receives and validates the published signal.          |
//| It deliberately contains NO trade/order functions.                |
//+------------------------------------------------------------------+
#property strict
#property version   "0.1"
#property description "Safe signal receiver for Alhaidani; monitoring only."

input string SignalUrl = "https://raw.githubusercontent.com/azzam774169177-jpg/alhaidani-gold-analyzer/mt5-bridge-demo/signal.json";
input int PollSeconds = 5;

datetime last_log_time = 0;
string last_status = "";

string JsonString(const string json, const string key)
{
   string needle = "\"" + key + "\"";
   int p = StringFind(json, needle);
   if(p < 0) return "";
   p = StringFind(json, ":", p + StringLen(needle));
   if(p < 0) return "";
   p++;
   while(p < StringLen(json) && (StringGetCharacter(json,p)==' ' || StringGetCharacter(json,p)=='\t')) p++;
   if(p >= StringLen(json) || StringGetCharacter(json,p)!='"') return "";
   p++;
   int e = StringFind(json, "\"", p);
   if(e < 0) return "";
   return StringSubstr(json, p, e-p);
}

void CheckSignal()
{
   char post[];
   char result[];
   string response_headers;
   ArrayResize(post, 0);
   ResetLastError();
   int http = WebRequest("GET", SignalUrl, "", 7000, post, result, response_headers);
   if(http != 200)
   {
      string err = "Receiver: HTTP/WebRequest failure " + IntegerToString(http) +
                   " | terminal error " + IntegerToString(GetLastError());
      Comment(err, "\nAdd https://raw.githubusercontent.com to MT5 WebRequest allow-list.");
      return;
   }

   string json = CharArrayToString(result, 0, -1, CP_UTF8);
   string signal = JsonString(json, "signal");
   string mode = JsonString(json, "execution_mode");
   string proxy = JsonString(json, "market_proxy");
   string source = JsonString(json, "data_source");
   string reason = JsonString(json, "reason");
   string symbol = JsonString(json, "symbol");

   string status = "BLOCKED";
   string explanation = "Signal is not approved for execution.";
   if(signal == "WAIT")
      explanation = "WAIT signal - no trade.";
   else if(mode == "SIGNALS_ONLY")
      explanation = "SIGNALS_ONLY mode - execution disabled.";
   else if(proxy == "GC=F" || StringFind(source, "GC=F") >= 0)
      explanation = "GC=F is an indicative COMEX proxy, not Weltrade execution pricing.";
   else if(signal != "BUY" && signal != "SELL")
      explanation = "Unknown signal value - rejected.";

   string display = "ALHAIDANI BRIDGE RECEIVER (MONITOR ONLY)\n" +
                    "Symbol: " + symbol + "\n" +
                    "Signal: " + signal + "\n" +
                    "Mode: " + mode + "\n" +
                    "Feed: " + proxy + "\n" +
                    "Status: " + status + "\n" +
                    "Reason: " + reason + "\n" + explanation +
                    "\nNO ORDERS ARE SENT BY THIS EA.";
   Comment(display);

   if(status != last_status || TimeCurrent() - last_log_time >= 60)
   {
      Print(display);
      last_status = status;
      last_log_time = TimeCurrent();
   }
}

int OnInit()
{
   EventSetTimer(MathMax(1, PollSeconds));
   Print("Alhaidani safe receiver started. Monitoring only; trading functions are absent.");
   CheckSignal();
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Comment("");
}

void OnTimer()
{
   CheckSignal();
}
