
import time
import requests
import hmac
from hashlib import sha256

APIURL = "https://open-api.bingx.com"

APIKEY = "tv4fY73fsWEXDMYcXWteUz2lZzhUi9SZMCQxGrvTfPjBjl1a32RzV0Gl2uY2mms5oCupIZyi1LvHRAKKMwdoQ"
SECRETKEY = "SvFtQv9Gk3isJ54qLWgy5Brn4vvx3bcpBUvE2kQJQuuzjQFtslWu2DSkIy0uUBnXdRTuxVdDuy5xVhw"

def demo():
    payload = {}
    path = '/openApi/swap/v2/trade/order/test'
    method = "POST"
    paramsMap = {
    "symbol": "BTC-USDT",
    "side": "BUY",
    "positionSide": "LONG",
    "type": "MARKET",
    "quantity": 5,
    "takeProfit": "{\"type\": \"TAKE_PROFIT_MARKET\", \"stopPrice\": 31968.0,\"price\": 31968.0,\"workingType\":\"MARK_PRICE\"}"
}
    paramsStr = parseParam(paramsMap)
    return send_request(method, path, paramsStr, payload)

def get_sign(api_secret, payload):
    signature = hmac.new(api_secret.encode("utf-8"), payload.encode("utf-8"), digestmod=sha256).hexdigest()
    print("sign=" + signature)
    return signature


def send_request(method, path, urlpa, payload):
    url = "%s%s?%s&signature=%s" % (APIURL, path, urlpa, get_sign(SECRETKEY, urlpa))
    print(url)
    headers = {
        'X-BX-APIKEY': APIKEY,
    }
    response = requests.request(method, url, headers=headers, data=payload)
    return response.text

def parseParam(paramsMap):
    sortedKeys = sorted(paramsMap)
    paramsStr = "&".join(["%s=%s" % (x, paramsMap[x]) for x in sortedKeys])
    if paramsStr != "": 
     return paramsStr+"&timestamp="+str(int(time.time() * 1000))
    else:
     return paramsStr+"timestamp="+str(int(time.time() * 1000))


if __name__ == '__main__':
    print("demo:", demo())
