#imports
import urllib.request as ul
from bs4 import BeautifulSoup as soup

#TEST
#Base data for selecting url with appropriate lat and lon
#TODO make a user input for lat and lon
#lat lon finder: https://www.latlong.net/
test_url_raw = 'https://forecast.weather.gov/MapClick.php?lat=40.3100&lon=-75.1305'
test_url_head = 'https://forecast.weather.gov/MapClick.php?lat='
test_lat = 40.3100
test_lon = -75.1305

test_lat_round = round(test_lat, 2)
test_lon_round = round(test_lon, 2)

test_url_compiled = test_url_head + str(test_lat_round) + "&lon=" + str(test_lon_round)

#DEBUG
print("Test url compiled: ")
print(test_url_compiled)


#TODO BeutifulSoup to extract the barometric pressure and the altitude
#FIXME is this overkill?
url = test_url_compiled
req = ul.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
client = ul.urlopen(req)
htmldata = client.read()
client.close()

pagesoup = soup(htmldata, "html.parser")

#DEBUG
print("HTML data: ")
print(pagesoup)

#pressure = <div class="pull-left" id="current_conditions_detail"> ... <b>Barometer</b> ...
#altitude = <div id="about_forecast"> ... 


#TODO calculate the local barometric pressure from the input lat+lon
#get station pressure and the elevation from the webpage
#do math and get the local barometric pressure =  25.4 * (NWS_pressure - (local_alt_in_FEET/1000))