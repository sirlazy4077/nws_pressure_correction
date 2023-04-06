#This program is designed to output altitude-corrected barometric pressure calculated from the pressure
#of the local NWS nearest to the given latitude and longitude using the user's estimated elevation
#the local NWS barometric pressure and estimated elevation are found by passing the user's lat and lon
#to a generated url for the NWS, which are pulled via BeutifulSoup4 into the program
#This url is provided to the user for them to verify the input data
#
#if user input is not functioning, change the following values to run the program on your local computer:
#(i.e. use ctrl+F to find and update the corresponding variable value currently set)
#hard_coded_lat
#hard_coded_lon
#hard_coded_temp
#
#Cheers! -Kevin Risolo, MMP, DABR (kprisolo@gmail.com)
#
#
#For the coders out there:
#TODO take input temperature from user to calculate Ctp instead of hard coding
#
#TODO take additional input temperature and input pressure to print a comparison report
#
#TODO define a strip and check input function (check input is a valid number)
#strip the input of whitespace
#1) check it's a float
#2) check the lat is between -90 and 90
#3) check the lon is between -180 and 180
#
#TODO define a check webpage function
#1) check that BeutifulSoup can parse the page (might not happen if above inputs don't output anything)

#imports
import urllib.request as ul
from bs4 import BeautifulSoup as soup

#TEST
#Base data for selecting url with appropriate lat and lon
test_url_raw = 'https://forecast.weather.gov/MapClick.php?lat=40.3100&lon=-75.1305'

hard_coded_lat = 40.3071
hard_coded_lon = -75.1477

#find your lat and lon here:
print("Find your lat and lon via this website, or another of your choice: ")
print('https://www.latlong.net/')
print()

#FIXME fix this so the user can input their own lat and lon, instead of hard-coding it
#TODO have this pass through a split/check input function for wider use
#input_lat_raw = input("Please input your latitude (ex: 40.3071): \n")
#input_lat = float(input_lat_raw)

#input_lon_raw = input("Please input your longitude (ex: -75.1477): \n")
#input_lon = float(input_lon_raw)


#TODO comment out below two test-only lines when input is configured
lat = hard_coded_lat
lon = hard_coded_lon

#TODO uncomment below when user input is working
#lat = input_lat
#lon = input_lon

lat_round = round(lat, 3)
lon_round = round(lon, 3)


#the url which will generate a NWS page for the given lat and lon to pull from
#TODO have this pass through a check function to make sure the lat and lon make a NWS page that exists
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

#DEBUG
#Use to pull a txt file of the html to visually parse
#print("HTML data: ")
#print(pagesoup)

#Use to find all id tags on the page
#ids = [tag['id'] for tag in pagesoup.select('div[id]')]
#print(ids)

current_conditions_detail = [i.text for i in pagesoup.find_all(id='current_conditions_detail')]
#DEBUG
#pressure_id = current_conditions_detail
#print(current_conditions_detail[0].split('\n\n'))

curr_cond_det_split = current_conditions_detail[0].split('\n\n')
curr_cond_baro_line = curr_cond_det_split[3].split('\n')
curr_cond_baro_line_split = curr_cond_baro_line[2].split(' ')

#This is the barometric pressure of the local NWS station
curr_cond_baro = curr_cond_baro_line_split[0]

#DEBUG
print("Here is the pulled barometric pressure for the local NWS station: ")
print(curr_cond_baro + " inHG")
print()


#altitude = <div id="about_forecast">
about_forecast = [i.text for i in pagesoup.find_all(id='about_forecast')]
about_forecast_split = about_forecast[0].split('\n\n')
about_forecast_elev_line = about_forecast_split[1]
about_forecast_elev_split_elev = about_forecast_elev_line.split('(Elev. ')
about_forecast_elev_space = about_forecast_elev_split_elev[1].split(' ')

#This is the altitude of the given lat+lon
about_forecast_elev = about_forecast_elev_space[0]

#DEBUG
print("Here is the pulled altitde for the given lat and lon: ")
print(about_forecast_elev + " feet")
print()


#TODO calculate the local barometric pressure from the input lat+lon
#get station pressure and the elevation from the webpage
#do math and get the local barometric pressure =  25.4 * (NWS_pressure - (local_alt_in_FEET/1000))

baro_lat_lon = round(25.4 * (float(curr_cond_baro) - (float(about_forecast_elev)/1000)), 2)
print("Here is your local barometric pressure provided in mmHg,\n for the given lat " +
      str(lat_round) + " and lon " + str(lon) + ",\n whose altitude is " +
      str(about_forecast_elev) + "feet,\n converted from NWS pressure of " +
      str(curr_cond_baro) + "inHg:")
print(str(baro_lat_lon) + " mmHg")
print()


#now calculate Ctp from the found pressure and the given vault temperature
#TODO comment out when user input is defined
hard_coded_temp = 20.0
temp_raw = hard_coded_temp

temp_float = float(temp_raw)
temp_round = round(temp_float,2)

ctp = round(((273.2 + temp_round) / (273.2 + 20.0)) * (760.0 / baro_lat_lon), 3)

print("Your Ctp for the given temperature of " + str(temp_raw) + "°C and pressure of " +
      str(baro_lat_lon) + "mmHg is: ")
print(str(ctp))