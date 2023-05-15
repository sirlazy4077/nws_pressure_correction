import urllib.request as ul
from bs4 import BeautifulSoup as soup

hard_coded_lat = 40.3071 #DEBUG
hard_coded_lon = -75.1477 #DEBUG

lat = hard_coded_lat #DEBUG
lon = hard_coded_lon #DEBUG

lat_round = round(lat, 3)
lon_round = round(lon, 3)

#the url which will generate a NWS page for the given lat and lon to pull from
url_head = "https://www.wunderground.com/hourly/"

url_compiled = url_head + str(lat_round) + "," + str(lon_round)

print("url compiled from given lat and lon, click to verify pressure and altitude/elevation: ")
print(url_compiled)
print()


#BeutifulSoup to extract the barometric pressure and the altitude
url = url_compiled
req = ul.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
client = ul.urlopen(req)
htmldata = client.read()
client.close()

pagesoup = soup(htmldata, "html.parser")

# Use to pull a txt file of the html to visually parse #DEBUG
print("HTML data: ") #DEBUG
# print(pagesoup) #DEBUG
# Use to find all id tags on the page #DEBUG
ids = [tag['id'] for tag in pagesoup.select('div[id]')] #DEBUG
print("IDs: ")
print(ids) #DEBUG
print()
# print("Classes: ")
