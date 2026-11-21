//+------------------------------------------------------------------+
//| Alhaidani MT5 Bridge - DEMO ONLY                                 |
//| Polls the project's public signal.json and can execute DEMO trades|
//| Live accounts are deliberately blocked in this build.            |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "Alhaidani signal bridge. Demo-only safety build."

#include <Trade/Trade.mqh>
CTrade trade;

input string SignalURL = "https://raw.githubusercontent.com/azzam774169177-jpg/alhaidani-gold-analyzer/main/signal.json";
input string TradeSymbol = "XAUUSD";
input double Lots = 0.01;
input int PollSeconds = 5;
input int MaxSignalAgeSeconds = 180;
input int MaxSpreadPoints = 100;
input int MaxDeviationPoints = 30;
input int MaxOpenPositions = 1;
input ulong MagicNumber = 7112026;
input bool EnableDemoTrading = false; // Must be enabled manually after DEMO testing.

string lastSignalKey = "";

string JsonValue(const string json, const string key)
{
   string needle = "\"" + key + "\"";
   int p = StringFind(json, needle);
   if(p < 0) return "";
   p = StringFind(json, ":", p + StringLen(needle));
   if(p < 0) return "";
   p++;
   while(p < StringLen(json) && (StringGetCharacter(json,p)==' ' || StringGetCharacter(json,p)=='\n' || StringGetCharacter(json,p)=='\r' || StringGetCharacter(json,p)=='\t')) p++;
   if(p >= StringLen(json)) return "";
   if(StringGetCharacter(json,p)=='"')
   {
      int q = StringFind(json, "\"", p+1);
      if(q < 0) return "";
      return StringSubstr(json,p+1,q-p-1);
   }
   int q = p;
   while(q < StringLen(json) && StringGetCharacter(json,q)!=',' && StringGetCharacter(json,q)!='}' && StringGetCharacter(json,q)!='\n' && StringGetCharacter(json,q)!='\r') q++;
   string v = StringSubstr(json,p,q-p);
   StringTrimLeft(v); StringTrimRight(v);
   return v;
}

bool GetSignalTime(const string value, datetime &result)
{
   if(StringLen(value) < 19) return false;
   string s = StringSubstr(value,0,19);
   StringReplace(s,"T"," ");
   StringReplace(s,"-",".");
   result = StringToTime(s) - (TimeLocal()-TimeGMT()); // convert parsed local time back to UTC
   return (result > 0);
}

int CountOurPositions()
{
   int count=0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket>0 && PositionGetString(POSITION_SYMBOL)==TradeSymbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC)==MagicNumber) count++;
   }
   return count;
}

void CheckSignal()
{
   char data[], result[];
   string headers;
   ResetLastError();
   int status=WebRequest("GET",SignalURL,"","",8000,data,0,result,headers);
   if(status!=200)
   {
      Print("Bridge: signal download failed. HTTP=",status," error=",GetLastError());
      return;
   }
   string json=CharArrayToString(result,0,-1,CP_UTF8);
   string signal=JsonValue(json,"signal");
   string mode=JsonValue(json,"execution_mode");
   string symbol=JsonValue(json,"symbol");
   string stamp=JsonValue(json,"updated_utc");
   if(signal!="BUY" && signal!="SELL") return;
   if(mode!="AUTO_DEMO") { Print("Bridge blocked: execution_mode must be AUTO_DEMO."); return; }
   if(symbol!="XAUUSD") { Print("Bridge blocked: unexpected signal symbol ",symbol); return; }
   if(!EnableDemoTrading) { Print("Bridge ready but disabled. EnableDemoTrading remains false."); return; }

   datetime signalTime;
   if(!GetSignalTime(stamp,signalTime)) { Print("Bridge blocked: invalid signal timestamp."); return; }
   long age=(long)(TimeGMT()-signalTime);
   if(age<0 || age>MaxSignalAgeSeconds) { Print("Bridge blocked: stale signal age=",age," seconds."); return; }

   string key=signal+"_"+stamp;
   if(key==lastSignalKey) return;
   string slText=JsonValue(json,"stop_loss");
   string tpText=JsonValue(json,"take_profit_1");
   if(slText=="" || tpText=="" || slText=="null" || tpText=="null") return;
   double sl=StringToDouble(slText), tp=StringToDouble(tpText);
   if(sl<=0 || tp<=0) return;

   if(!TerminalInfoInteger(TERMINAL_CONNECTED) || !MQLInfoInteger(MQL_TRADE_ALLOWED) || !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)) return;
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO)
   {
      Print("SAFETY BLOCK: this EA only trades DEMO accounts.");
      return;
   }
   if(!SymbolSelect(TradeSymbol,true)) { Print("Bridge: symbol unavailable: ",TradeSymbol); return; }
   MqlTick tick;
   if(!SymbolInfoTick(TradeSymbol,tick)) return;
   double point=SymbolInfoDouble(TradeSymbol,SYMBOL_POINT);
   if(point<=0 || (tick.ask-tick.bid)/point>MaxSpreadPoints) { Print("Bridge blocked: spread too high."); return; }
   if(CountOurPositions()>=MaxOpenPositions) { Print("Bridge blocked: max positions reached."); return; }

   double price=(signal=="BUY"?tick.ask:tick.bid);
   int digits=(int)SymbolInfoInteger(TradeSymbol,SYMBOL_DIGITS);
   sl=NormalizeDouble(sl,digits); tp=NormalizeDouble(tp,digits);
   if(signal=="BUY" && !(sl<price && tp>price)) { Print("Bridge blocked: invalid BUY SL/TP."); return; }
   if(signal=="SELL" && !(tp<price && sl>price)) { Print("Bridge blocked: invalid SELL SL/TP."); return; }

   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(MaxDeviationPoints);
   bool ok=false;
   if(signal=="BUY") ok=trade.Buy(Lots,TradeSymbol,0.0,sl,tp,"Alhaidani "+key);
   else ok=trade.Sell(Lots,TradeSymbol,0.0,sl,tp,"Alhaidani "+key);
   if(ok)
   {
      lastSignalKey=key;
      Print("DEMO ORDER SENT: ",signal," ",TradeSymbol," lots=",Lots," SL=",sl," TP=",tp);
   }
   else Print("Order failed: ",trade.ResultRetcode()," ",trade.ResultRetcodeDescription());
}

int OnInit()
{
   if(PollSeconds<1 || Lots<=0) return INIT_PARAMETERS_INCORRECT;
   EventSetTimer(PollSeconds);
   Print("Alhaidani MT5 Bridge loaded. DEMO ONLY; live trading is blocked.");
   Print("Add https://raw.githubusercontent.com to MT5: Tools > Options > Expert Advisors > Allow WebRequest.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); }
void OnTimer() { CheckSignal(); }
