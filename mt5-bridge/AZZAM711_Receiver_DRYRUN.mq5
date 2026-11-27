//+------------------------------------------------------------------+
//| AZZAM711_Receiver_DRYRUN.mq5                                      |
//| Secure queue connectivity test only. NEVER sends trade orders.   |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "AZZAM711 authenticated MT5 queue receiver - DRY RUN ONLY"

input string BridgeBaseUrl = "https://alhaidani-gold-photo-bot-production.up.railway.app";
input string BridgeSecret = ""; // Set locally in MT5; never share it.
input long   RequiredAccountLogin = 28913511;
input string RequiredServer = "Weltrade-Real";
input int    PollSeconds = 5;

string ExtractJsonString(const string json,const string key)
{
   string needle = "\"" + key + "\":\"";
   int p = StringFind(json,needle);
   if(p < 0) return "";
   p += StringLen(needle);
   int q = StringFind(json,"\"",p);
   if(q < 0) return "";
   return StringSubstr(json,p,q-p);
}

void PollBridge()
{
   if(StringLen(BridgeSecret) < 24)
   {
      Print("AZZAM711: Set BridgeSecret in EA inputs. No request sent.");
      return;
   }
   if(AccountInfoInteger(ACCOUNT_LOGIN) != RequiredAccountLogin ||
      AccountInfoString(ACCOUNT_SERVER) != RequiredServer)
   {
      Print("AZZAM711 BLOCKED: Wrong MT5 account/server. Current login=",
            AccountInfoInteger(ACCOUNT_LOGIN)," server=",AccountInfoString(ACCOUNT_SERVER));
      return;
   }

   string url = BridgeBaseUrl + "/bridge/next";
   string headers = "Authorization: Bearer " + BridgeSecret + "\r\n";
   char data[];
   char result[];
   string result_headers;
   ResetLastError();
   int status = WebRequest("GET",url,headers,5000,data,result,result_headers);
   if(status == -1)
   {
      Print("AZZAM711 WebRequest failed. Error=",GetLastError(),
            ". Add the Railway HTTPS domain to MT5 Tools > Options > Expert Advisors > Allow WebRequest.");
      return;
   }
   if(status != 200)
   {
      Print("AZZAM711 HTTP status=",status," body=",CharArrayToString(result));
      return;
   }

   string body = CharArrayToString(result);
   if(StringFind(body,"\"command\":null") >= 0)
   {
      Print("AZZAM711: Connected; queue empty. DRY RUN; no trades.");
      return;
   }

   string symbol = ExtractJsonString(body,"symbol");
   string action = ExtractJsonString(body,"action");
   if(symbol != "XAUUSD")
   {
      Print("AZZAM711 BLOCKED: Non-XAUUSD command received. No trades.");
      return;
   }
   Print("AZZAM711 DRY RUN RECEIVED: action=",action,
         " symbol=",symbol," payload=",body,
         " | NOT EXECUTED; command NOT acknowledged.");
}

int OnInit()
{
   if(RequiredAccountLogin != 28913511)
   {
      Print("AZZAM711: Account guard mismatch; initialization refused.");
      return INIT_FAILED;
   }
   if(!EventSetTimer(MathMax(1,PollSeconds)))
      return INIT_FAILED;
   Print("AZZAM711 DRY RUN initialized. Account=",AccountInfoInteger(ACCOUNT_LOGIN),
         " Server=",AccountInfoString(ACCOUNT_SERVER),
         ". No trade functions are present in this EA.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   PollBridge();
}

void OnTick()
{
   // Intentionally empty. DRY RUN ONLY.
}
