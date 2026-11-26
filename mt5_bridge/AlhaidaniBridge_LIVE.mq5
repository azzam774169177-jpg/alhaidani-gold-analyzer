//+------------------------------------------------------------------+
//| AlhaidaniBridge_LIVE - local signal bridge for MT5               |
//| Reads MQL5/Files/Common/Alhaidani/signal.json (FILE_COMMON).      |
//| Live execution is OFF by default and requires explicit inputs.   |
//+------------------------------------------------------------------+
#property strict
#property version "1.10"
#property description "Local XAUUSD signal bridge. Risk-gated; disabled by default."
#include <Trade/Trade.mqh>
CTrade trade;

input string SignalFile = "Alhaidani\\signal.json";
input string TradeSymbol = "XAUUSD";
input int PollSeconds = 2;
input int MaxSignalAgeSeconds = 180;
input int MaxSpreadPoints = 100;
input int MaxDeviationPoints = 30;
input double Lots = 0.01;
input double MaxRiskPercent = 1.0;
input ulong MagicNumber = 7112026;
input bool EnableLiveTrading = false; // Explicit opt-in after testing.
input bool EnableDemoTrading = false;

string lastSignalId = "";
ulong managedTicket = 0;
bool tp1Done = false, tp2Done = false;

string J(const string j,const string k)
{
 string n="\""+k+"\""; int p=StringFind(j,n); if(p<0)return "";
 p=StringFind(j,":",p+StringLen(n)); if(p<0)return ""; p++;
 while(p<StringLen(j) && (StringGetCharacter(j,p)==' ' || StringGetCharacter(j,p)=='\n' || StringGetCharacter(j,p)=='\r' || StringGetCharacter(j,p)=='\t'))p++;
 if(p>=StringLen(j))return "";
 if(StringGetCharacter(j,p)=='\"'){int q=StringFind(j,"\"",p+1); if(q<0)return ""; return StringSubstr(j,p+1,q-p-1);}
 int q=p; while(q<StringLen(j) && StringGetCharacter(j,q)!=',' && StringGetCharacter(j,q)!='}' && StringGetCharacter(j,q)!='\n' && StringGetCharacter(j,q)!='\r')q++;
 string v=StringSubstr(j,p,q-p); StringTrimLeft(v); StringTrimRight(v); return v;
}
bool ReadSignal(string &j)
{
 int h=FileOpen(SignalFile,FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
 if(h==INVALID_HANDLE){Print("Bridge: cannot open Common Files/",SignalFile,". Put signal.json there.");return false;}
 j=""; while(!FileIsEnding(h)) j+=FileReadString(h); FileClose(h); return StringLen(j)>10;
}
int OurPosition()
{
 for(int i=PositionsTotal()-1;i>=0;i--){ulong t=PositionGetTicket(i);
  if(t>0 && PositionGetString(POSITION_SYMBOL)==TradeSymbol && (ulong)PositionGetInteger(POSITION_MAGIC)==MagicNumber)return (int)t;}
 return -1;
}
bool ParseTime(string s,datetime &t)
{
 if(StringLen(s)<19)return false; s=StringSubstr(s,0,19); StringReplace(s,"T"," "); StringReplace(s,"-",".");
 t=StringToTime(s)-(TimeLocal()-TimeGMT()); return t>0;
}
double NormVol(double v)
{
 double step=SymbolInfoDouble(TradeSymbol,SYMBOL_VOLUME_STEP), mn=SymbolInfoDouble(TradeSymbol,SYMBOL_VOLUME_MIN), mx=SymbolInfoDouble(TradeSymbol,SYMBOL_VOLUME_MAX);
 if(step<=0)return 0; v=MathFloor(v/step)*step; if(v<mn || v>mx)return 0;
 return NormalizeDouble(v,2);
}
void ManageTargets()
{
 if(!PositionSelect(TradeSymbol))return;
 if((ulong)PositionGetInteger(POSITION_MAGIC)!=MagicNumber)return;
 ulong ticket=(ulong)PositionGetInteger(POSITION_TICKET);
 if(ticket!=managedTicket){managedTicket=ticket;tp1Done=false;tp2Done=false;}
 long typ=PositionGetInteger(POSITION_TYPE); double entry=PositionGetDouble(POSITION_PRICE_OPEN);
 double sl=PositionGetDouble(POSITION_SL), tp=PositionGetDouble(POSITION_TP), vol=PositionGetDouble(POSITION_VOLUME);
 double p=SymbolInfoDouble(TradeSymbol,(typ==POSITION_TYPE_BUY)?SYMBOL_BID:SYMBOL_ASK);
 double pt=SymbolInfoDouble(TradeSymbol,SYMBOL_POINT);
 // TP levels are stored in terminal global variables when the order is opened.
 string prefix="AH711_"+(string)ticket+"_";
 double t1=GlobalVariableGet(prefix+"T1"),t2=GlobalVariableGet(prefix+"T2");
 bool hit1=(typ==POSITION_TYPE_BUY?p>=t1:p<=t1), hit2=(typ==POSITION_TYPE_BUY?p>=t2:p<=t2);
 if(!tp1Done && hit1)
 {
  double part=NormVol(vol/3.0);
  if(part>0 && part<vol) trade.PositionClosePartial(ticket,part);
  double protect=NormalizeDouble(entry+(typ==POSITION_TYPE_BUY?5*pt:-5*pt),(int)SymbolInfoInteger(TradeSymbol,SYMBOL_DIGITS));
  if((typ==POSITION_TYPE_BUY && protect>sl) || (typ==POSITION_TYPE_SELL && (sl==0 || protect<sl))) trade.PositionModify(ticket,protect,tp);
  tp1Done=true; Print("TP1 reached; partial close attempted and protective SL moved to +5 points.");
 }
 if(!tp2Done && hit2 && tp1Done)
 {
  if(PositionSelectByTicket(ticket)){vol=PositionGetDouble(POSITION_VOLUME);double part=NormVol(vol/2.0);if(part>0 && part<vol)trade.PositionClosePartial(ticket,part);}
  tp2Done=true; Print("TP2 reached; second partial close attempted.");
 }
}
void CheckSignal()
{
 string j; if(!ReadSignal(j))return;
 string sig=J(j,"signal"), sym=J(j,"symbol"), mode=J(j,"execution_mode");
 if((sig!="BUY" && sig!="SELL") || sym!=TradeSymbol)return;
 string stamp=J(j,"updated_utc"); datetime st; if(!ParseTime(stamp,st))return;
 long age=(long)(TimeGMT()-st); if(age<0 || age>MaxSignalAgeSeconds){Print("Blocked stale signal: ",age);return;}
 string id=J(j,"signal_id"); if(id=="")id=sig+"_"+stamp;
 if(id==lastSignalId)return;
 if(OurPosition()>0){ManageTargets();return;}
 long accountMode=AccountInfoInteger(ACCOUNT_TRADE_MODE);
 bool permitted=(accountMode==ACCOUNT_TRADE_MODE_REAL && EnableLiveTrading) || (accountMode==ACCOUNT_TRADE_MODE_DEMO && EnableDemoTrading);
 if(!permitted){Print("Bridge loaded; execution disabled or account mode not explicitly enabled.");return;}
 if(!TerminalInfoInteger(TERMINAL_CONNECTED) || !MQLInfoInteger(MQL_TRADE_ALLOWED) || !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))return;
 if(!SymbolSelect(TradeSymbol,true))return;
 MqlTick tick; if(!SymbolInfoTick(TradeSymbol,tick))return;
 double point=SymbolInfoDouble(TradeSymbol,SYMBOL_POINT);
 if(point<=0 || (tick.ask-tick.bid)/point>MaxSpreadPoints){Print("Blocked: spread too high.");return;}
 double sl=StringToDouble(J(j,"stop_loss")), t1=StringToDouble(J(j,"take_profit_1")), t2=StringToDouble(J(j,"take_profit_2")), t3=StringToDouble(J(j,"take_profit_3"));
 double entry=(sig=="BUY"?tick.ask:tick.bid), vol=NormVol(Lots);
 if(vol<=0 || sl<=0 || t1<=0 || t2<=0 || t3<=0)return;
 bool valid=(sig=="BUY" && sl<entry && t1>entry && t2>t1 && t3>t2) || (sig=="SELL" && sl>entry && t1<entry && t2<t1 && t3<t2);
 if(!valid){Print("Blocked: invalid entry/SL/TP order.");return;}
 double loss=0; if(!OrderCalcProfit(sig=="BUY"?ORDER_TYPE_BUY:ORDER_TYPE_SELL,TradeSymbol,vol,entry,sl,loss))return;
 double equity=AccountInfoDouble(ACCOUNT_EQUITY);
 if(equity<=0 || MathAbs(loss)>equity*MaxRiskPercent/100.0){Print("Blocked: estimated SL risk exceeds ",MaxRiskPercent,"% equity. Risk=",MathAbs(loss)," equity=",equity);return;}
 trade.SetExpertMagicNumber(MagicNumber); trade.SetDeviationInPoints(MaxDeviationPoints);
 bool ok=(sig=="BUY")?trade.Buy(vol,TradeSymbol,0,sl,t3,"Alhaidani "+id):trade.Sell(vol,TradeSymbol,0,sl,t3,"Alhaidani "+id);
 if(ok && trade.ResultRetcode()==TRADE_RETCODE_DONE)
 {
  lastSignalId=id; managedTicket=trade.ResultOrder(); tp1Done=false;tp2Done=false;
  GlobalVariableSet("AH711_"+(string)managedTicket+"_T1",t1); GlobalVariableSet("AH711_"+(string)managedTicket+"_T2",t2);
  Print("Order accepted. Three-stage management armed. Verify position ticket and broker execution.");
 } else Print("Order rejected: ",trade.ResultRetcode()," ",trade.ResultRetcodeDescription());
}
int OnInit(){if(PollSeconds<1 || Lots<=0 || MaxRiskPercent<=0)return INIT_PARAMETERS_INCORRECT;trade.SetExpertMagicNumber(MagicNumber);EventSetTimer(PollSeconds);Print("Alhaidani local bridge initialized. Live=",EnableLiveTrading," Demo=",EnableDemoTrading,". Common file: ",SignalFile);return INIT_SUCCEEDED;}
void OnDeinit(const int r){EventKillTimer();}
void OnTimer(){ManageTargets();CheckSignal();}
