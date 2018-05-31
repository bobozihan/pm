# -*- coding: utf-8 -*-
VERSION="20180424"

import tornado.ioloop
import tornado.web
import os,sys,time,datetime,json,socket,xlrd
import redis
import MySQLdb
from tool import *

CONFIGJSON="config.json"

SIDE_DICT={
'BuyOpen':'1_1','BuyClose':'1_2','SellOpen':'2_1','SellClose':'2_2',
'EquityBuy':'1_','EquitySell':'2_',
'BondBuy':'3_','BondSell':'4_','Repo':'5_','AntiRepo':'6_'
}

MULTIPLIER={'IF':300,'IC':200,'IH':300}
CONFIG={}
fundlist={}

reload(sys)
sys.setdefaultencoding("gbk")


def xVal(name="",date="",code2product={},Index={}):
    IndexMap={"IF":"000300","IH":"000016","IC":"000905"}
    Val={"pos":{},"shares":0,"io":0,u"净值":0,u"利息收入":0,u"管理费":0,u"交易费":0,u"托管费":0,u"其它应付款":0,u"应交税费":0}
    if name=="" or date=="":
        return Val
    product=name.split("-")[-1]
    try:
        data = xlrd.open_workbook(CONFIG["PATH"]["GZB"]+product+"/"+date+".xls")
    except:
        return Val
    table = data.sheet_by_index(0)
    header={}
    
    for i in range(1,table.nrows):
        row=table.row_values(i)
        if len(header)==0 and u"科目代码" in row:
            for c in range(len(row)):
                header[row[c].replace(" ","")]=c
        elif len(header):
            code=str(row[header[u"科目代码"]]).replace(":","").replace(u"：","")
            entry=str(row[header[u"科目名称"]]).replace("\n","").replace(" ","").replace(u"Ａ","A")
            shares=row[header[u"数量"]]
            unitcost=row[header[u"单位成本"]]
            value=row[header[u"市值"]]
            if len(code)==0:
                continue
            if code in [u"委托资产净值",u"资产资产净值",u"基金资产净值",u"集合计划资产净值"]:
                Val[u"净值"]=float(value)                

            elif code in [u"委托资产往来",u"实收资本",u"实收基金"]:
                Val["shares"]=0 if str(shares)=="" else float(str(shares).replace(",",""))
                #Val["shares"]=float(str(shares).replace(",",""))
            elif entry==u"应收申购款" and len(code)==4:
                Val["io"]+=value

            elif entry==u"应付赎回款" and len(code)==4:
                Val["io"]-=value

            elif entry==u"应收利息" and len(code)==4:
                Val[u"利息收入"]+=value

            elif entry==u"应付利息" and len(code)==4:
                Val[u"利息收入"]-=value
            
            elif entry in [u"应交税费",u"应交税金"] and len(code)==4:
                Val[u"应交税费"]-=value

            elif entry in [u"应付受托费",u"应付管理人报酬"] and len(code)==4:
                Val[u"管理费"]-=value
            elif entry in [u"应付托管费"] and len(code)==4:
                Val[u"托管费"]-=value
            elif entry in [u"应付交易费用",u"应付佣金"] and len(code)==4:
                Val[u"交易费"]-=value
            elif entry in [u"应付账款",u"预提费用",u"其它应付款"] and len(code)==4:
                Val[u"其它应付款"]-=value
            elif entry==u"中金现金管家货币B":
                continue
            elif shares!="" and unitcost!="" and value!="" and entry!="":
                symbol=code[-6:]
                if symbol in code2product:
                    x=xVal(name+"-"+code2product[symbol],date,code2product,Index)
                    r=shares/x["shares"]
                    Val[u"应交税费"]+=  x[u"应交税费"] *r
                    Val[u"其它应付款"]+=x[u"其它应付款"]*r
                    Val[u"托管费"]+=x[u"托管费"]*r
                    Val[u"管理费"]+=x[u"管理费"]*r
                    Val[u"交易费"]+=x[u"交易费"]*r
                    Val[u"利息收入"]  +=x[u"利息收入"]  *r
                    for p in x["pos"]:
                        Val["pos"][p]={"s":x["pos"][p]["s"]*r,"v":x["pos"][p]["v"]*r,"n":x["pos"][p]["n"]}
                else:
                    vi=0
                    cn=str(symbol[0:2])
                    if cn in IndexMap:
                        vi=shares*Index[IndexMap[cn]]*MULTIPLIER[cn]*(1 if value>0 else -1)
                        nk=name+"-"+cn+"0000"
                        if Val["pos"].has_key(nk):
                            old=Val["pos"][nk]
                            Val["pos"][nk]["s"]+=shares
                            Val["pos"][nk]["v"]+=vi
                        else:
                            Val["pos"][nk]={"s":shares,"v":vi,"n":cn+"0000"}
                        vi=value-vi
                        k=name+"-"+code
                        if Val["pos"].has_key(k):
                            Val["pos"][k]["s"]+=shares
                            Val["pos"][k]["v"]+=vi
                        else:
                            Val["pos"][k]={"s":shares,"v":vi,"n":symbol+u"基差"}
                    else:
                        k=name+"-"+code
                        if Val["pos"].has_key(k):
                            Val["pos"][k]["s"]+=shares
                            Val["pos"][k]["v"]+=value                            
                        else:
                            Val["pos"][k]={"s":shares,"v":value,"n":entry}
                    
    if CONFIG["productList"][product]["type"]==u"指数加":
        f = file(CONFIG["PATH"]["report"]+product+".csv",'r')
        for row in f.read().split("\n"):
            r=row.split(",")
            if r[0]==date:
                Val["pos"][name+"-Ashare"]={"s":float(r[9]),"v":-float(r[1])*float(r[9]),"n":product}
                Val["shares"]=float(r[8])
                Val[u"净值"] =float(r[7])-float(r[9])*float(r[1])
    return Val

def cal(product,startdate,enddate,POS,SECTOR,Group,code2product):
    Group=json.loads(Group)
    sectors={}
    if SECTOR<2:
        f=file(CONFIG["PATH"]["fromWinddb"]+'AShareIndustriesClass.txt','rb')
        for row in f.read().split("\n"):        
            r=row.split(",")
            if len(r)==2:
                g=u"股票"+ ("-"+r[1].decode("utf8") if SECTOR==1 else "" )
                Group[r[0]]=g
                sectors[g]=0
        f.close()

    f=file(CONFIG["PATH"]["fromWinddb"]+'benchmark.txt','r') 
    IndexPrice={}
    for row in f.read().split("\n"):
        r=row.split(",")
        if r[0]>=startdate and r[0]<=enddate:
            if not IndexPrice.has_key(r[0]):
                IndexPrice[r[0]]={}
            IndexPrice[r[0]][r[1]]=float(r[2])
    f.close()
    dates=sorted(IndexPrice.keys())
    N=len(dates)-1
    assets=[u"__份额__",u"净值",u"申赎款项",u"交易损益",u"管理费",u"托管费",u"交易费",u"其它应付款",u"应交税费",u"利息收入"]
    for a in sectors:
        assets.append(a)
    Assets={}
    for g in assets:
         Assets[g]=[0 for i in range(N)]

    Val_=xVal(product,dates[0],code2product,IndexPrice[dates[0]])
    for d in range(N):
        Val=xVal(product,dates[d+1],code2product,IndexPrice[dates[d+1]] )
        if Val[u"净值"]==0:
            Val=Val_.copy()
        Assets[u"__份额__"][d]=Val["shares"]   
        Assets[u"申赎款项"][d]= Val["io"]
        Assets[u"净值"][d]=      Val[u"净值"]-(Val_[u"净值"] if not POS else 0)
        Assets[u"其它应付款"][d]= Val[u"其它应付款"]-(Val_[u"其它应付款"] if not POS else 0)
        Assets[u"应交税费"][d]=  Val[u"应交税费"]-  (Val_[u"应交税费"] if not POS else 0)
        Assets[u"利息收入"][d]=  Val[u"利息收入"]-  (Val_[u"利息收入"] if not POS else 0)
        Assets[u"管理费"][d]=    (Val[u"管理费"]-(Val_[u"管理费"] if not POS else 0)) if Val_[u"管理费"]>Val[u"管理费"] else 0
        Assets[u"托管费"][d]=    (Val[u"托管费"]-(Val_[u"托管费"] if not POS else 0) ) if Val_[u"托管费"]>Val[u"托管费"] else 0
        Assets[u"交易费"][d] =   (Val[u"交易费"]-(Val_[u"交易费"] if not POS else 0)) if Val_[u"交易费"]>Val[u"交易费"] else 0
        
        Assets[u"交易损益"][d]= (Assets[u"净值"][d] - Assets[u"申赎款项"][d]-\
                    Assets[u"其它应付款"][d]-Assets[u"管理费"][d]-Assets[u"托管费"][d]-Assets[u"交易费"][d]-\
                    Assets[u"应交税费"][d]-Assets[u"利息收入"][d]) if not POS else 0
        for s in Val_["pos"]:
            if Val["pos"].has_key(s):
                p= Val["pos"][s]["v"] - Val_["pos"][s]["v"]/Val_["pos"][s]["s"]*Val["pos"][s]["s"]
                Assets[u"交易损益"][d]-=0 if POS else p
                t=s[-6:]
                if Group.has_key(t):
                    t=Group[t]
                else:
                    t+=u"_"+Val_["pos"][s]["n"]
                
                if not Assets.has_key(t):
                    assets.append(t)
                    Assets[t]= [0 for i in range(N)]
                Assets[t][d]+=Val["pos"][s]["v"] if POS else p

        Val_=Val.copy()

    data=[]    
    for a in assets:
        row={"a":a}
        s=0
        for d in range(N):
            s+=Assets[a][d] if not POS else 0
            row[dates[d+1]]=round(Assets[a][d],2)
        row["sum"]=round(s,2) if a!=u"__份额__" else Assets[a][0]
        data.append(row)
    return data

def parseLeg(leg,parentId,taskId):
    if not leg.has_key('leadLeg') and not leg.has_key('lagLeg'):
        batch_id=str(int(taskId)*10000+int(leg['legId']))       
        tot=0
        account_codes=[]
        accounts=[]
        for instru in leg['instructions']:
            multiply= MULTIPLIER[instru['symbol'][0:2]] if MULTIPLIER.has_key(instru['symbol'][0:2]) else 1
            amount=int(instru['shares'])*float(instru['price'])*multiply
            tot=tot+amount
            i=0
            if instru["accountCode"] not in account_codes:
                account_codes.append(instru["accountCode"])
                accounts.append({
                    "id":batch_id+"_"+instru["accountCode"],
                    "name":(fundlist[instru["accountCode"]] if fundlist.has_key(instru["accountCode"]) else "")+"("+instru["accountCode"]+")",
                    "instru_number":0,
                    "target":0,
                    "deal":0,
                    "impact":0,
                    "impact_p":0,
                    "progress":0,
                    "deal_time":0,
                    "instructions":[]
                    })
                i=len(account_codes)-1
            else:
                i=account_codes.index(instru["accountCode"])
            accounts[i]["instru_number"]+=1
            accounts[i]["instructions"].append(instru)
            accounts[i]["target"]+=amount

        return {
                    "id":batch_id,
                    "name":leg['legName'],
                    "children":accounts,
                    "target":round(tot,2),
                    "instru_number":len(leg['instructions']),
                    "deal":0,
                    "deal_time":0,
                    "impact":0,
                    "impact_p":0,
                    "progress":0

                }
    else:
        Id=str(parentId)+"_"+str(leg['legId'])
        children=[]
        target=0
        instru_number=0
        if leg.has_key('leadLeg'):
            leadleg=parseLeg(leg['leadLeg'],Id,taskId)
            target+=leadleg['target']
            instru_number+=leadleg['instru_number']
            if len(leadleg['children']):
                children.append(leadleg)
        if leg.has_key('lagLeg'):
            lagleg=parseLeg(leg['lagLeg'],Id,taskId)
            target+=lagleg['target']
            instru_number+=lagleg['instru_number']
            if len(lagleg['children']):
                children.append(lagleg)

        return {
                    "id":Id,
                    "name":leg['legName'],
                    "children":children,
                    "target":target,
                    "instru_number":instru_number,
                    "deal":0,
                    "deal_time":0,
                    "impact":0,
                    "impact_p":0,
                    "progress":0
                }

def aggr(queryresult,task_json,status,Price):
    if task_json.has_key('children'):
        rows=[]
        children=[]
        deal=0
        impact=0
        deal_time=0
        fee=0
        profit=0
        for child in task_json['children']:
            rows_child=aggr(queryresult,child,status,Price)
            deal+=rows_child['deal']
            impact+=rows_child['impact']
            fee+=rows_child['fee']
            profit+=rows_child['profit']
            deal_time=max(rows_child['deal_time'], deal_time)
            children.append(rows_child)

        progress=round(100*deal/task_json['target'],2) if task_json['target']!=0 else 100    

        return {"id":"Task_"+str(task_json['id']),
                "name":task_json['name'],
                "target":task_json["target"],
                "instru_number":task_json["instru_number"],
                "children":children,
                "deal":round(deal,2),
                "impact":round(impact,2),
                "impact_p":round(impact/deal*100,2) if deal>0 else 0,
                "fee":round(fee,2),
                "fee_p":round(fee/deal*100,2) if deal>0 else 0,
                "profit":round(profit,2),
                "progress":progress,
                "status":status,
                "deal_time":deal_time,
                "state":"closed"
                }

    else:
        impact=0
        deal=0
        fee=0
        profit=0
        symbols={}
        for instru in task_json['instructions']:
            symbols[instru['symbol']+"_"+SIDE_DICT[instru["side"]]]=instru['price']
        #symbols=[instru['symbol'] ]
        deal_time=0
        for r in queryresult:
            if str(r[0])==task_json['id']:
                symbol=str(r[1])
                deal_amount=int(r[3])
                deal_price=float(r[4])/deal_amount
                deal_time=max(r[5], deal_time)                
                multiply=MULTIPLIER[r[1][0:2]] if MULTIPLIER.has_key(r[1][0:2]) else 1
                target_price=symbols[str(r[1])+"_"+str(r[2])] if symbols.has_key(symbol+"_"+str(r[2])) else 10000
                deal+=target_price*deal_amount*multiply
                impact+=(target_price -deal_price)*deal_amount*multiply*(1 if r[2][0]=="1" else -1)
                profit+=(Price[symbol]-deal_price)*deal_amount*multiply*(1 if r[2][0]=="1" else -1)
                fee+=float(r[6])
                
        progress=round(100*deal/task_json['target'],2) if task_json['target']!=0 else 100
        return {"id":"Task_"+str(task_json['id']),
                "name":task_json['name'],
                "target":task_json["target"],
                "instru_number":task_json["instru_number"],
                "children":[],
                "deal":deal,
                "impact":round(impact,2),
                "impact_p":round(impact/deal*100,2) if deal>0 else 0,
                "fee":round(fee,2),
                "fee_p":round(fee/deal*100,2) if deal>0 else 0,
                "profit":round(profit,2),
                "progress":progress,
                "status":status,
                "deal_time":deal_time
                }

def get_batch_target(batch_no,task_json):
    if task_json.has_key('children'):
        stock_target=[]
        
        for child in task_json['children']:
            child_stock=get_batch_target(batch_no,child)

            if child_stock:
                stock_target.extend(child_stock)
        return stock_target
    elif task_json['id'] in batch_no:
        stock_target=[]

        for instru in task_json['instructions']:

            stock_target.append({
                                    "id":str(task_json['id'])+"_"+str(instru['symbol']).lower()+"_"+str(instru['combNo'])+"_"+str(SIDE_DICT[str(instru['side'])]),
                                    "batch_no":task_json['id'].split("_")[0],
                                    "symbol":str(instru['symbol']),
                                    "combNo":str(instru['combNo']),
                                    "accountCode":fundlist[instru["accountCode"]] if fundlist.has_key(instru["accountCode"]) else instru["accountCode"],
                                    "side":instru['side'],
                                    "shares":instru['shares'],
                                    "price":round(instru['price'],3),                                    
                                    "progress":0 if instru['shares'] else 100                            
                                })
        return stock_target

def query_taskjson(ID,date):
    cur_deal.execute("select taskjson,status from task where id like '"+ID+"' and TRADEDATE="+date) 
    return cur_deal.fetchall()

def control(ID,status,today):    
    cur_deal.execute("UPDATE ufx.task SET status="+status+" WHERE id="+ID+" and tradedate="+today)                

def getStatus(ID,today):
    cur_deal.execute("SELECT status FROM ufx.task WHERE id="+ID+" and tradedate="+today)
    res = cur_deal.fetchall()
    status=0
    if len(res):                
        status=int(res[0][0])
    return status

def batch_detail(batch_account_no,date):
    Price=getPrice()
    batch_no=[0]
    account_code="("
    for b in batch_account_no:
        ba=b.split("_")
        batch_no.append(int(ba[0]))
        account_code+=("'"+str(ba[1])+"',")
    account_code+="'')"
    
    queryresult=query_taskjson(str(batch_no[1]/10000),date)
    task=json.loads(str(queryresult[0][0]))
    leg=parseLeg(task['leg'],task['taskId'],task['taskId'])        
    task_json={
        "id":task['taskId'],
        "name":task['name']+" - "+task['leg']['legName']+" ("+task['filename']+")",
        "children":leg['children'],
        "target":leg['target'],
        "instru_number":leg['instru_number']
    }
    stock_target=get_batch_target(batch_account_no,task_json)
    stock_target=sorted(stock_target, key=lambda x:x['id'])
    
    if not len(stock_target):
         return        
    # query message and update
    cur_deal.execute("SELECT concat(batch_no,'_',account_code,'_',lower(stock_code),'_',combi_no,'_',entrust_direction,'_',futures_direction) as id,sum(convert(deal_amount,DECIMAL)),sum(convert(deal_amount,DECIMAL)*deal_price),max(deal_time),sum(deal_fee)\
              from \
              (select * from ufx.message\
              where batch_no in %s and account_code in "+account_code+" and deal_date= %s and  deal_amount!='' \
              group by deal_no ) as b\
              group by futures_direction,entrust_direction,combi_no,stock_code,account_code,batch_no\
              order by id",
              args=[batch_no,date]
#                      args=[batch_no,"20180126"]
            )
    queryresult= cur_deal.fetchall()

    if len(queryresult):
        i=0
        for t in range(0,len(stock_target)):
            r=queryresult[i]
            if r[0]==stock_target[t]['id']:
                if i<len(queryresult)-1:
                    i=i+1
                multiply= MULTIPLIER[stock_target[t]['symbol'][0:2]] if MULTIPLIER.has_key(stock_target[t]['symbol'][0:2]) else 1
                stock_target[t]["deal_amount"]=float(r[1])
                stock_target[t]["deal_amt"]=float(r[2])*multiply
                stock_target[t]["deal_price"]=round(float(r[2])/stock_target[t]["deal_amount"],3)                
                stock_target[t]["fee"]=float(r[4])
                stock_target[t]["lastprice"]=Price[stock_target[t]['symbol']]
                stock_target[t]["profit"]=(stock_target[t]["lastprice"]-stock_target[t]["deal_price"])*multiply* (1 if "Buy" in stock_target[t]["side"] else -1)
                stock_target[t]["impact"]=(stock_target[t]["price"]    -stock_target[t]["deal_price"])* (1 if "Buy" in stock_target[t]["side"] else -1)
                stock_target[t]["impact_p"]=stock_target[t]["impact"]/stock_target[t]["deal_price"]*100
                stock_target[t]["progress"]=100*float(r[1])/stock_target[t]["shares"]
                stock_target[t]["deal_time"]=r[3]
    return stock_target

def getPrice():
    global red
    Price={}
    stock=red.hgetall("stock")
    CTP=red.hgetall("CTP")
    fund=red.hgetall("fund")
    for i in stock:
        Price[i]=float(stock[i].split("|")[1])
    for i in CTP:
        Price[i]=float(CTP[i].split("|")[1])
    for i in fund:
        Price[i]=float(fund[i].split("|")[1])
    return Price

def updateTask():
    global red,cur_deal    
    today=red.hget("date","today")
    task_status={}
    task_json=[]
    batch_no=[0]
    queryresult=query_taskjson("%",today)
    if len(queryresult)==0:        
        return
    for r in queryresult:
        task=json.loads(str(r[0]))
        batch_no.append(task['taskId'])
        task_status[task['taskId']]=int(r[1])
        
        leg=parseLeg(task['leg'],task['taskId'],task['taskId'])        
        task_json.append({
            "id":task['taskId'],
            "name":task['name']+" - "+task['leg']['legName']+" ("+task['filename']+")",
            "children":leg['children'],
            "target":leg['target'],
            "instru_number":leg['instru_number']
        })
    cur_deal.execute("SELECT concat(batch_no,'_',account_code),stock_code,concat(entrust_direction,'_',futures_direction),sum(convert(deal_amount,DECIMAL)),sum(convert(deal_amount,DECIMAL)*deal_price) ,max(deal_time),sum(deal_fee)\
                    from \
                (select * from message\
                where total_deal_amount!='' and floor(batch_no/10000) in %s and deal_date=%s \
                group by deal_no,batch_no) as b\
                group by futures_direction,entrust_direction,combi_no,stock_code,account_code,batch_no" , 
                args=[batch_no,today]
                )
    
    queryresult=cur_deal.fetchall()
    
    for t in task_json:
        red.hset("taskjson",t["id"],json.dumps(aggr(queryresult,t,task_status[t["id"]],getPrice())))

def gettime():
    return time.strftime("%F %T",time.localtime(time.time()))

def err():
    return gettime()+"\tError Sending Message"

def restart():
    os.popen("kill `ps -ef |grep PM\ -m|grep -v grep|awk '{print $2}'`")
    os.popen("cpp/PM -m &")

def setDate(date):
    today_real=time.strftime("%Y%m%d",time.localtime(time.time()))
    date= today_real if date=="" or date>=today_real else date                
    yesterday=""
    today=""
    
    with open(CONFIG["PATH"]["fromWinddb"]+"tradedate.txt","r") as f:
        for d in f.read().split("\n"):                
            if len(d)<8:
                continue
            if int(d)>int(date):
                break
            yesterday=today
            today=d
    red.hmset("date",{"today":today,"yesterday":yesterday})
    red.delete("taskjson")
    restart()
    
    
def config_database():
    global red,cur_deal,CONFIG,fundlist
    f=file(CONFIGJSON,'r')
    CONFIG=json.loads(f.read())
    f.close()
    for p in CONFIG["productList"]:
        fundlist[CONFIG["productList"][p]["AccountCode"]]=CONFIG["productList"][p]["name"]
    
    red=redis.StrictRedis(host=CONFIG["redis"]["ip"],port=CONFIG["redis"]["port"],db=0)
    
    conn_deal=MySQLdb.connect(
        host=CONFIG['mysql']['host'],
        user=CONFIG['mysql']['user'],
        passwd=CONFIG['mysql']['passwd'],
        db=CONFIG['mysql']['db'],
        charset="utf8")
    cur_deal=conn_deal.cursor()
    print >> sys.stderr, gettime(),"database connected"

class CookieHandler(tornado.web.RequestHandler):
    def get_current_user(self):        
        if CONFIG["userIP"].has_key(self.request.remote_ip):
            v=CONFIG["userIP"][self.request.remote_ip].split(".")
            cookie={"name":v[0],"job":v[1]}
            if not self.request.uri in ["/data?p=11","/data?p=21","/data?p=0"]:
                print >> sys.stderr, gettime(),cookie["name"],cookie["job"],self.request.uri
            return cookie
        else:
            print >> sys.stderr,gettime(), self.request.remote_ip,self.request.uri

class Login(CookieHandler):    
    def get(self):
        if CONFIG["userIP"].has_key(self.request.remote_ip):            
            self.redirect(self.get_argument("next"))
        else:
            self.write(self.request.remote_ip+" is not an authorized user.")


class Main(CookieHandler):
    @tornado.web.authenticated
    def get(self):
        self.render("main.html")

class Help(CookieHandler):
    @tornado.web.authenticated
    def get(self):        
        self.render("help/help.html",VERSION=VERSION)

class Data(CookieHandler):
    @tornado.web.authenticated
    def get(self):        
        global red
        p= self.get_argument('p')
        response={
            "version":VERSION,
            "header":json.loads(red.get("header")),
            "tasks":[],
            "market":[],
            "model":[],
            "product":[]
        }
        if p[0]=="2":
            response["tasks"]=[json.loads(m) for m in red.hgetall("taskjson").values()]

        elif p[0]=="1" and self.current_user["job"] in ["pm","watcher","super"]:
            response["market"]=json.loads(red.get("spider"))
            for m in red.hgetall("model").values():
                try:
                    mm=json.loads(m)
                    response["model"].append(mm)
                except:
                    continue                
            monitor=red.hgetall("product")
            Schedule=red.hgetall("schedule")
            for m in sorted(Schedule):
                try:
                    product=json.loads(monitor[m])
                    schedule=json.loads(Schedule[m])
                except:
                    continue
                product["type"]=str(schedule["progress"])+"|"+schedule["timetrade"]
                summary={}
                if p[1]=="0":
                    try:                        
                        f=file(CONFIG["PATH"]["summary"]+product["id"]+"/"+schedule["timetrade"]+".json",'r')
                        summary=json.loads(f.read())
                        f.close()
                    except:
                        summary={}
        
                if schedule["timetrade"]!="" and len(summary):
                    children=summary.pop("children")
                    product.update(summary)            
                    for i in product["children"]:
                        if children.has_key(i["N"]):                                                        
                            i.update(children[i["N"]])            
                            del children[i["N"]]

                    for N in children:
                        c={"id":product["id"]+"_"+N,"N":N,"R":0,"A":0,"T":"0.00","Nav":0}
                        c.update(children[N])
                        product["children"].append(c)
                product["state"]="closed"
                response["product"].append(product)            
        self.write(json.dumps(response))     

        
class Job(CookieHandler):
    @tornado.web.authenticated
    def post(self):
        global red,CONFIG,fundlist
        user_job=self.current_user["job"]
        if not user_job in ["pm","super"]:
            return
        if self.request.arguments.has_key("p"): 
            p=self.request.arguments["p"][0]
            newSchedule=json.loads(self.request.arguments["schedule"][0])
            if p=="all":
                for product in newSchedule:
                    old=json.loads(red.hget("schedule",product))
                    old.update(newSchedule[product])
                    r=red.hset("schedule",product,json.dumps(old,indent=4))
                self.write("done")
            else:
                old=json.loads(red.hget("schedule",p))
                old.update(newSchedule)
                r=red.hset("schedule",p,json.dumps(old))
                self.write(str(r))

        elif self.request.arguments.has_key("config"):
            config=self.request.arguments["config"][0]
            with open(CONFIGJSON, 'w') as f:  
                f.write(config)
            f=file(CONFIGJSON,'r')
            CONFIG_NEW=json.loads(f.read())
            f.close()
            if CONFIG_NEW!=CONFIG:                
                CONFIG=CONFIG_NEW.copy()                
                for p in CONFIG["productList"]:
                    fundlist[CONFIG["productList"][p]["AccountCode"]]=CONFIG["productList"][p]["name"]   
            self.write("done")

        elif self.request.arguments.has_key("today"):
            date =self.request.arguments["today"][0]
            setDate(date)
            self.write("done")

    @tornado.web.authenticated
    def get(self):        
        global red
        user_job=self.current_user["job"]
        cmd= self.get_argument('cmd')        
        today=red.hget("date","today")
        response=""
        if cmd=="reherse":
            start = self.request.arguments['start'][0]
            end   = self.request.arguments['end'][0]
            models= self.request.arguments['models'][0]
            index = self.request.arguments['index'][0]
            trade = self.request.arguments['trade'][0]
            fee = self.request.arguments['fee'][0]
            freq = self.request.arguments['freq'][0]
            response=os.popen("cpp/Strats -r "+start+" "+end+" "+models+" "+index+" "+trade+" "+fee+" "+freq).read()
            
        elif cmd=="getModel":
            p=self.get_argument('p')
            response=os.popen("cpp/Strats -n "+p).read()

        elif cmd=="getStrats":
            response=os.popen("cpp/Strats -l").read()

        elif cmd in ["a","t","n"]:
            p=self.get_argument('p')
            response=os.popen("cpp/Report -"+cmd+" "+p).read()

        elif cmd in ["i","c","v","u","d","s","f","b"] and user_job in ["pm","super"]:
            p=self.get_argument('p').replace("\n","").replace("\"","\\\"")
            response=os.popen("cpp/PM -"+cmd+" "+p).read()
            if cmd in ["f","v","u"]:
                restart()                 

        elif cmd=="listProduct" and user_job in ["pm","super"]:
            res=[]
            schedule=red.hgetall("schedule")
            product=red.hgetall("product")
            for r in sorted(schedule):
                p=json.loads(product[r])                
                res.append({"value":p["id"],"text":p["N"]})
            response=json.dumps(res)
        
        elif cmd=="listInstru" and user_job in ["pm","super"]:
            res=[]
            schedule=red.hgetall("schedule")
            for p in sorted(schedule):
                sc=json.loads(schedule[p])
                if CONFIG["productList"][p]["tool"]=="UFX" and len(sc["confirmed"]):
                    for i in sorted(sc["confirmed"]):
                        f=p+"-"+i+".csv"
                        res.append({"value":f,"text":f})
            response=json.dumps(res)

        elif cmd=="getAttr" and user_job in ["pm","super"]:
            p=self.get_argument('p')
            startdate=self.get_argument('startdate')
            enddate=self.get_argument('enddate')
            pos=int(self.get_argument('pos'))
            sector=int(self.get_argument('sector'))
            Group=self.get_argument('group')
            code2product=json.loads(self.get_argument("productMap"))            
            response=json.dumps(cal(p,startdate,enddate,pos,sector,Group,code2product))
        
        elif cmd=="getSchedule" and user_job in ["pm","super"]:
            p= self.get_argument('p')
            if p=="all":
                res=red.hgetall("schedule")
                scheduleAll={}
                for p in  res:
                     scheduleAll[p]=json.loads(res[p])
                response=json.dumps(scheduleAll,indent=4)    
            else:
                response=json.dumps(json.loads(red.hget("schedule",p)),indent=4)

        elif cmd=="getConfig" and user_job in ["pm","super"]:
            f=open(CONFIGJSON,"r")
            response=f.read()
            f.close()
            
        elif cmd=="checklog" and user_job in ["pm","super"]:
            try:
                f=open(CONFIG["PATH"]["log"]+today+".log")
                response=f.read()
                f.close()
            except:
                response=""

        elif cmd=="control":
            isTrader=user_job in ["trader","super"]
            status=self.get_argument("status")
            if status=="4" or isTrader:
                control(self.get_argument('id')[5:],self.get_argument('status'),today)
            response=str(int(isTrader))

        elif cmd=="getStatus":            
            response=json.dumps({
                "status":getStatus(self.get_argument("id")[5:],today),
                "isTrader": int(user_job in ["trader","super"]) 
            })            
        
        elif cmd=="ufx":
            batch_account_no=[i[5:] for i in self.get_argument("p").split(",")]
            response=json.dumps(batch_detail(batch_account_no,today))
        
        self.write(response)

class Tool(CookieHandler):
    @tornado.web.authenticated
    def get(self):        
        usetool(self)

def Crontab():
    global red,CONFIG
    if "08:00:" in gettime():
        setDate("")

    if red.hget("date","today")!=time.strftime("%Y%m%d",time.localtime(time.time())):
        return

    
    if "08:25:" in gettime():
        os.popen("cpp/PM -s all")
        os.popen("cpp/PM -v "+(",".join(red.hgetall("schedule").keys()))+" &" )

    if "08:30:" in gettime():
        for m in CONFIG["modelList"]:
            os.popen("cpp/Strats -h "+m+" &")


    if "08:30:" in gettime() or "09:30:" in gettime():
        for m in CONFIG["productList"]:
            os.popen("cpp/Report -r "+m+" &")

    if "14:30:" in gettime():
        Schedule=red.hgetall("schedule")
        Product=red.hgetall("product")
        for p in Schedule:
            product=json.loads(Product[p])
            s=json.loads(Schedule[p])
            for c in product["children"]:
                if c["N"]=="IPO":                    
                    s["Composite"]={"security":{},"future":{},"commodity":{},"equity": {"IPO":0}}
                    s["isDelta"]=0
                    s["progress"]=10
                    s["rebalance"]=0                    
                    red.hset("schedule",p,json.dumps(s).replace(" ","") )
                    break
        os.popen("cpp/PM -i "+(",".join(Schedule.keys()))+" &" )

    if "18:00:" in gettime():
        monitorjson={        
            "benchmark":json.loads(red.get("header")),
            "model":[json.loads(m) for m in red.hgetall("model").values()],
            "product":[]    
        }    
        Product =red.hgetall("product")
        Schedule=red.hgetall("schedule")

        for name in Schedule:
            s=json.loads(Schedule[name])        
            if Product.has_key(name):
                try:
                    product=json.loads(Product[name])       
                except:
                    continue
               
                product["confirmed"]=s["confirmed"]
                del product["N"]
                monitorjson["product"].append(product)

         
        fl=open('snapshot/'+monitorjson["benchmark"]["date"]+".json", 'w')
        fl.write(json.dumps(monitorjson,indent=4))
        fl.close()




if __name__ == "__main__":    
    config_database()
    
    settings = {
        "static_path":"./static",
        "template_path":"./static",
        "cookie_secret": gettime(),
        "login_url": "/login",
        "debug":True,
    }

    app = tornado.web.Application([    
        (r"/login",Login),    
        (r"/job",Job),
        (r"/data",Data),
        (r"/",Main),
        (r"/help",Help),
        (r"/tool",Tool),    
    ],**settings)
    app.listen(80) 
    tornado.ioloop.PeriodicCallback(updateTask,    3000).start()    
    tornado.ioloop.PeriodicCallback(Crontab,   60000).start()
    tornado.ioloop.IOLoop.instance().start()
    
