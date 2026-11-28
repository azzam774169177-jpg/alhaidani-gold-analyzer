//+------------------------------------------------------------------+
//| AZZAM711_LIVE.mq5                                                |
//| Authenticated XAUUSD spot signal receiver for MetaTrader 5       |
//| Live trading is guarded by account, server, symbol and risk inputs|
//+------------------------------------------------------------------+
#property strict
#property version   "1.11"
#property description "AZZAM711 authenticated live XAUUSD receiver"

#include <Trade/Trade.mqh>
CTrade trade;

input string BridgeBaseUrl = "https://alhaidani-gold-photo-bot-production.up.railway.app";
input string BridgeSecret = "";
input long   RequiredAccountLogin = 28913511;
input string RequiredServer = "Weltrade-Real";
input string TradeSymbol = "XAUUSD";
input double TradeVolume = 0.01;                // Editable lot size
input int    PollSeconds = 5;
input int    MaxSpreadPoints = 100;
input int    MaxDeviationPoints = 30;
input ulong  MagicNumber = 7112026;
input bool   EnableLiveTrading = false;         // Must be enabled explicitly in EA inputs
input bool   OnePositionAtATime = true;

string last_status = "";

string JsonString(const string json,const string key)
{
   string needle = "\"" + key + "\"";
   int p = StringFind(json,needle);
   if(p < 0) return "";
   p = StringFind(json,":",p + StringLen(needle));
   if(p < 0) return "";
   p++;
   while(p < StringLen(json) && (StringGetCharacter(json,p)==' ' ||
         StringGetCharacter(json,p)=='\t' || StringGetCharacter(json,p)=='\r' ||
         StringGetCharacter(json,p)=='\n')) p++;
   if(p >= StringLen(json) || StringGetCharacter(json,p)!='"') return "";
   p++;
   string out = "";
   bool escaped = false;
   for(int i=p;i<StringLen(json);i++)
   {
      ushort c = StringGetCharacter(json,i);
      if(escaped) { out += ShortToString(c); escaped=false; continue; }
      if(c=='\\') { escaped=true; continue; }
      if(c=='"') break;
      out += ShortToString(c);
   }
   return out;
}

double JsonNumber(const string json,const string key)
{
   string needle = "\"" + key + "\"";
   int p = StringFind(json,needle);
   if(p < 0) return 0.0;
   p = StringFind(json,":",p + StringLen(needle));
   if(p < 0) return 0.0;
   p++;
   while(p < StringLen(json) && (StringGetCharacter(json,p)==' ' ||
         StringGetCharacter(json,p)=='\t')) p++;
   int e=p;
   while(e < StringLen(json))
   {
      ushort c=StringGetCharacter(json,e);
      if((c>='0' && c<='9') || c=='-' || c=='+' || c=='.') e++;
      else break;
   }
   if(e<=p) return 0.0;
   return StringToDouble(StringSubstr(json,p,e-p));
}

bool AuthorizedAccount()
{
   if(AccountInfoInteger(ACCOUNT_LOGIN)!=RequiredAccountLogin) return false;
   if(AccountInfoString(ACCOUNT_SERVER)!=RequiredServer) return false;
   if(_Symbol!=TradeSymbol) return false;
   return true;
}

bool HasOurPosition()
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket>0 && PositionGetString(POSITION_SYMBOL)==TradeSymbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC)==MagicNumber) return true;
   }
   return false;
}

bool HttpGet(const string path,string &body)
{
   char data[],result[];
   string response_headers;
   ArrayResize(data,0);
   string headers="Authorization: Bearer "+BridgeSecret+"\r\nCache-Control: no-cache\r\n";
   ResetLastError();
   int code=WebRequest("GET",BridgeBaseUrl+path,headers,8000,data,result,response_headers);
   if(code!=200)
   {
      Print("AZZAM711 HTTP GET failed. code=",code," error=",GetLastError());
      return false;
   }
   body=CharArrayToString(result,0,-1,CP_UTF8);
   return true;
}

bool HttpAck(const string id)
{
   string payload="{\"id\":\""+id+"\"}";
   char data[],result[];
   string response_headers;
   int n=StringToCharArray(payload,data,0,WHOLE_ARRAY,CP_UTF8);
   if(n>0) ArrayResize(data,n-1);
   string headers="Authorization: Bearer "+BridgeSecret+"\r\nContent-Type: application/json\r\n";
   ResetLastError();
   int code=WebRequest("POST",BridgeBaseUrl+"/bridge/ack",headers,8000,data,result,response_headers);
   if(code!=200)
   {
      Print("AZZAM711 ACK failed. code=",code," error=",GetLastError());
      return false;
   }
   return true;
}

void ProcessQueue()
{
   string body;
   if(!HttpGet("/bridge/next",body)) return;
   string id=JsonString(body,"id");
   if(id=="") return;
   int cp=StringFind(body,"\"command\"");
   if(cp<0) { Print("AZZAM711: malformed queue response"); return; }
   string command=StringSubstr(body,cp);
   string action=JsonString(command,"action");
   string symbol=JsonString(command,"symbol");

   string gv="AZZAM711_DONE_"+IntegerToString((long)MagicNumber)+"_"+id;
   if(GlobalVariableCheck(gv)) { HttpAck(id); return; }

   if(action!="OPEN" || symbol!=TradeSymbol)
   {
      Print("AZZAM711 rejected unsupported command/action or symbol: ",action," / ",symbol);
      GlobalVariableSet(gv,TimeCurrent());
      HttpAck(id);
      return;
   }

   if(!EnableLiveTrading)
   {
      Print("AZZAM711 LIVE is disabled. Set EnableLiveTrading=true only after reviewing inputs.");
      return;
   }
   if(!AuthorizedAccount())
   {
      Print("AZZAM711 BLOCKED: account/server/chart does not match required live account.");
      return;
   }
   if(TradeVolume<=0 || !SymbolSelect(TradeSymbol,true))
   {
      Print("AZZAM711 BLOCKED: invalid volume or symbol unavailable.");
      return;
   }
   if(OnePositionAtATime && HasOurPosition())
   {
      Print("AZZAM711 BLOCKED: an AZZAM711 position is already open.");
      return;
   }

   MqlTick tick;
   if(!SymbolInfoTick(TradeSymbol,tick)) return;
   double spread=(tick.ask-tick.bid)/SymbolInfoDouble(TradeSymbol,SYMBOL_POINT);
   if(spread>MaxSpreadPoints)
   {
      Print("AZZAM711 BLOCKED: spread ",spread," exceeds limit ",MaxSpreadPoints);
      return;
   }

   double sl=JsonNumber(command,"stop_loss");
   double tp=JsonNumber(command,"target");
   double entry=JsonNumber(command,"entry");
   string side=JsonString(command,"side");
   if(sl<=0 || tp<=0 || entry<=0 || (side!="BUY" && side!="SELL"))
   {
      Print("AZZAM711 BLOCKED: signal is missing valid side/entry/SL/TP.");
      GlobalVariableSet(gv,TimeCurrent());
      HttpAck(id);
      return;
   }

   int digits=(int)SymbolInfoInteger(TradeSymbol,SYMBOL_DIGITS);
   sl=NormalizeDouble(sl,digits);
   tp=NormalizeDouble(tp,digits);
   double price=(side=="BUY" ? tick.ask : tick.bid);
   if(side=="BUY" && !(sl<price && tp>price))
   {
      Print("AZZAM711 BLOCKED: BUY SL/TP are on the wrong side of market.");
      GlobalVariableSet(gv,TimeCurrent()); HttpAck(id); return;
   }
   if(side=="SELL" && !(sl>price && tp<price))
   {
      Print("AZZAM711 BLOCKED: SELL SL/TP are on the wrong side of market.");
      GlobalVariableSet(gv,TimeCurrent()); HttpAck(id); return;
   }

   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(MaxDeviationPoints);
   trade.SetTypeFillingBySymbol(TradeSymbol);
   bool sent=false;
   if(side=="BUY")
      sent=trade.Buy(TradeVolume,TradeSymbol,0.0,sl,tp,"AZZAM711 "+id);
   else
      sent=trade.Sell(TradeVolume,TradeSymbol,0.0,sl,tp,"AZZAM711 "+id);

   uint rc=trade.ResultRetcode();
   if(sent && (rc==TRADE_RETCODE_DONE || rc==TRADE_RETCODE_PLACED || rc==TRADE_RETCODE_DONE_PARTIAL))
   {
      GlobalVariableSet(gv,TimeCurrent());
      Print("AZZAM711 LIVE ORDER ACCEPTED: ",side," ",TradeSymbol,
            " volume=",TradeVolume," SL=",sl," TP=",tp," ticket=",trade.ResultOrder());
      HttpAck(id);
   }
   else
   {
      Print("AZZAM711 ORDER FAILED: retcode=",rc," ",trade.ResultRetcodeDescription());
   }
}

int OnInit()
{
   if(BridgeSecret=="")
   {
      Print("AZZAM711: enter BridgeSecret privately in EA inputs.");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(PollSeconds<1 || TradeVolume<=0)
      return INIT_PARAMETERS_INCORRECT;
   trade.SetExpertMagicNumber(MagicNumber);
   EventSetTimer(PollSeconds);
   Print("AZZAM711 LIVE receiver loaded. LiveTrading=",EnableLiveTrading,
         " account=",AccountInfoInteger(ACCOUNT_LOGIN)," server=",AccountInfoString(ACCOUNT_SERVER));
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); }
void OnTimer() { ProcessQueue(); }
void OnTick() {}
