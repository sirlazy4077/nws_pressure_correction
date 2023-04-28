#START OF HEADER
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
#
#TODO take additional input temperature and input pressure to print a comparison report
#
#TODO is there a method to do this worldwide? another website which provides pressure and altitude from lat and lon?
#
#END OF HEADER

#START OF PROGRAM

#imports
import sys
import urllib.request as ul
from bs4 import BeautifulSoup as soup


#function to take user input
def get_input(y_n_question):
      input_user = input(y_n_question)
      
      #return yes as true, no as false
      yes_no_bool = False;
      input_cleaned = input_user.lower().strip()
      
      #check input is appropriate
      flag_loop = False;
      while(not flag_loop):
            if (input_cleaned == 'y'):
                  flag_loop = True;
                  yes_no_bool = True;
            elif (input_cleaned == 'n'):
                  flag_loop = True;
                  yes_no_bool = False;
            else:
                  print("Please type a valid input of 'y' or 'n'")
                  continue
            
      return yes_no_bool


#PART 1/3: Get pressure from lat and lon, corrected for altitude

#test_url_raw = 'https://forecast.weather.gov/MapClick.php?lat=40.3100&lon=-75.1305' #DEBUG
#hard_coded_lat = 40.3071 #DEBUG
#hard_coded_lon = -75.1477 #DEBUG

#find your lat and lon here:
print("Find your lat and lon via this website, or another of your choice: ")
print('https://www.latlong.net/')
print()

input_lat = round(float(input("What is your latitude? (ex: 40.3071): ")),4)
input_lon = round(float(input("What is your longitude? (ex: -75.1477): ")),4)

#lat = hard_coded_lat #DEBUG
#lon = hard_coded_lon #DEBUG
lat = input_lat
lon = input_lon

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

try:
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

      current_conditions_detail = [i.text for i in pagesoup.find_all(id='current_conditions_detail')]
      #pressure_id = current_conditions_detail #DEBUG
      #print(current_conditions_detail[0].split('\n\n')) #DEBUG
      
      curr_cond_det_split = current_conditions_detail[0].split('\n\n')
      curr_cond_baro_line = curr_cond_det_split[3].split('\n')
      curr_cond_baro_line_split = curr_cond_baro_line[2].split(' ')

      #This is the barometric pressure of the local NWS station
      curr_cond_baro = curr_cond_baro_line_split[0]
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
      print("Here is the pulled altitde for the given lat and lon: ")
      print(about_forecast_elev + " feet")
      print()


      #calculate the local barometric pressure from the input lat+lon
      #get station pressure and the elevation from the webpage
      #do math and get the local barometric pressure =  25.4 * (NWS_pressure - (local_alt_in_FEET/1000))
      baro_lat_lon = round(25.4 * (float(curr_cond_baro) - (float(about_forecast_elev)/1000)), 2)
      print("Here is your local barometric pressure provided in mmHg,\n for the given lat " +
            str(lat_round) + " and lon " + str(lon) + ",\n whose altitude is " +
            str(about_forecast_elev) + "feet,\n converted from NWS pressure of " +
            str(curr_cond_baro) + "inHg:")
      print(str(baro_lat_lon) + " mmHg")
      print()

      #conversions from mmHg to other pressure units commonly seen
      print("And here is your pressure in different units: ")
      print(str(round(baro_lat_lon,2)) + " Tor, kPa")
      baro_lat_lon_inHG = baro_lat_lon * 0.03937
      print(str(round(baro_lat_lon_inHG,3)) + " inHG")
      baro_lat_lon_hPa = baro_lat_lon * 1.33322
      print(str(round(baro_lat_lon_hPa,2)) + " hPa, mbar")
      baro_lat_lon_bar = baro_lat_lon_hPa * 0.001
      print(str(round(baro_lat_lon_bar,4)) + " bar")
      baro_lat_lon_Pa = baro_lat_lon_hPa * 133.322
      print(str(round(baro_lat_lon_Pa,1)) + " Pascal")
      print()
      
except IndexError:
      print("There was an error in processing this request.")
      print("Please check your lat and lon inputs are entered correctly.")
      print("Please note this program only functions for locations in the USA.")
      print("If inputs are correct, the NWS may be down. Please use alternative means for pressure readings.")
      print()
      


#PART 2/3: Calculate CTP

#now calculate Ctp from the found pressure and the given vault temperature
input_to_ctp = "Would you like to continue to Ctp with the above pressure? (y/n): "

#check input is appropriate or if user wants to exit
flag_to_ctp = False;
while(not flag_to_ctp):
      get_input(input_to_ctp)
      if (input_to_ctp):
            flag_to_ctp = True;
      elif (not input_to_ctp):
            sys.exit(0)
      else:
            continue

#hard_coded_temp = 20.0 #DEBUG
input_temp = round(float(input("What is your temperature, in Celsius? (ex: 20.0): ")),4)
temp_round = round(float(input_temp),2)
#temp_raw = hard_coded_temp #DEBUG
temp_raw = temp_round

ctp = round(((273.2 + temp_round) / (273.2 + 20.0)) * (760.0 / baro_lat_lon), 3)

print("Your Ctp for the given temperature of " + str(temp_raw) + "°C and pressure of " +
      str(baro_lat_lon) + "mmHg is: ")
print(str(ctp))


#TODO PART 3/3: Intercomparison


#END OF PROGRAM