#test_url_raw = 'https://forecast.weather.gov/MapClick.php?lat=40.3100&lon=-75.1305' #DEBUG
#hard_coded_lat = 40.3071 #DEBUG
#hard_coded_lon = -75.1477 #DEBUG

input_lat = round(get_num_input("What is your latitude? (ex: 40.3071): "),4)
input_lon = round(get_num_input("What is your longitude? (ex: -75.1477): "),4)

#lat = hard_coded_lat #DEBUG
#lon = hard_coded_lon #DEBUG
lat = input_lat
lon = input_lon

lat_round = round(lat, 3)
lon_round = round(lon, 3)


#the url which will generate a NWS page for the given lat and lon to pull from
url_head = 'https://forecast.weather.gov/MapClick.php?lat='

url_compiled = url_head + str(lat_round) + "&lon=" + str(lon_round)

print("url compiled from given lat and lon, click to verify pressure and altitude/elevation: ")
print(url_compiled)
print("Pressure is found near the top of the page, under Current Conditions at, next to the bold text Barometer (reported in inHG)")
print("Elevation is found towards the bottom right, below the map, next to the bold text Point Forecast (reported in feet)")
print()


#BeutifulSoup to extract the barometric pressure and the altitude
url = url_compiled
req = ul.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
client = ul.urlopen(req)
htmldata = client.read()
client.close()

pagesoup = soup(htmldata, "html.parser")

#Use to pull a txt file of the html to visually parse #DEBUG
#print("HTML data: ") #DEBUG
#print(pagesoup) #DEBUG
#Use to find all id tags on the page #DEBUG
#ids = [tag['id'] for tag in pagesoup.select('div[id]')] #DEBUG
#print(ids) #DEBUG