#START OF HEADER
#
#This program is designed to output altitude-corrected barometric pressure calculated from the pressure
#of the local NWS nearest to the given latitude and longitude using the user's estimated elevation
#the local NWS barometric pressure and estimated elevation are found by passing the user's lat and lon
#to a generated url for the NWS, which are pulled via BeutifulSoup4 into the program
#This url is provided to the user for them to verify the input data
#
#Cheers! -Kevin Risolo, MMP, DABR (kprisolo@gmail.com / sirlazy4077)
#
#
#For the coders out there:
#
#TODO is there a method to do this worldwide? another website which provides pressure and altitude from lat and lon?
#
#END OF HEADER


#START OF PROGRAM
#
#imports
import urllib.request as ul
from bs4 import BeautifulSoup as soup


#helper functions to take user input, one for y/n, and one for numbers
def get_input(y_n_question):
      #return yes as true, no as false
      yes_no_bool = False

      #check input y/n response is appropriate
      flag_loop = True
      while(flag_loop):
            #strip of whitespace, apply lower case, take only the first letter after that
            input_user = input(y_n_question)
            input_striplower = input_user.lower().strip()
            input_cleaned = input_striplower[:1]
            
            if (input_cleaned == 'y'):
                  flag_loop = False;
                  yes_no_bool = True;
            elif (input_cleaned == 'n'):
                  flag_loop = False;
                  yes_no_bool = False;
            else:
                  print("Please type a valid input of 'y' or 'n'")
            
      return yes_no_bool
# get_input("testing y/n question: ") #DEBUG

def get_num_input(num_input):
      #return a clean number input
      return_num = 0;
      
      #check input number is appropriate
      flag_loop = True
      while(flag_loop):
            input_num = input(num_input).strip()
            try:
                  float(input_num)
                  
            except:
                  print("Please enter a valid number (example format: 000.00)")
            
            else:
                  flag_loop = False
                  return_num = float(input_num)
                  return return_num
# get_num_input("what number to test: ") #DEBUG


#the main functions to pull pressure from input lat/lon and return altitude corrected pressure in mmHg,
# and to calc Ctp from that value,
# and to do intercomparsion with that value

#PART 1/3: Get pressure from lat and lon provided, corrected for altitude
def pressure():
      pressure_flag = True
      while(pressure_flag):
            try:
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
                  baro_lat_lon_Pa = baro_lat_lon * 133.322
                  print(str(round(baro_lat_lon_Pa,1)) + " Pascal")
                  print()
                  
            except IndexError:
                  print("There was an error in processing this request.")
                  print("Please check your lat and lon inputs are entered correctly.")
                  print("Please note this program only functions for locations in the USA.")
                  print("If inputs are correct, the NWS may be down. Please use alternative means for pressure readings.")
                  print()
            
            pressure_question = "Would you like to go back and change your lat/lon? (y/n): "
            pressure_input = get_input(pressure_question)
            if (pressure_input):
                  continue
            else:
                  pressure_flag = False
      return baro_lat_lon


#PART 2/3: Calculate CTP from the found pressure and the given vault temperature, return the temp entered
def ctp(baro_lat_lon):
      ctp_flag = True
      while(ctp_flag):
            #hard_coded_temp = 20.0 #DEBUG
            input_temp = get_num_input("What is your temperature, in Celsius? (ex: 20.0): ")
            temp_round = round(float(input_temp),2)
            #temp_raw = hard_coded_temp #DEBUG
            temp_raw = temp_round

            ctp = round(((273.2 + temp_round) / (273.2 + 20.0)) * (760.0 / baro_lat_lon), 3)

            print("Your Ctp for the given temperature of " + str(temp_raw) + "°C and pressure of " +
                  str(baro_lat_lon) + "mmHg is: ")
            print(str(ctp))
            print()
            
            ctp_question = "Would you like to go back and change your temperature? (y/n): "
            ctp_input = get_input(ctp_question)
            if (ctp_input):
                  continue
            else:
                  ctp_flag = False
      return temp_round


#PART 3/3: Intercomparison, return the intercomparison absolute and percent differences for temp and press
def intercomparison(baro_lat_lon, temp_round):
      intercomp_flag = True
      while(intercomp_flag):
            intercomp_temp = get_num_input("What is your temperature for intercomparison, in Celsius? (ex: 20.0): ")
            intercomp_temp_round = round(float(intercomp_temp),2)

            intercomp_baro = get_num_input("What is your pressure for intercomparison, in mmHg? (ex: 760.0): ")
            intercomp_baro_round = round(float(intercomp_baro),2)

            intercomp_temps_abs = round((intercomp_temp_round - temp_round),2)
            intercomp_temps_percent = round(((intercomp_temp_round - temp_round)/temp_round)*100,2)
            intercomp_temps_kelvin = round(((intercomp_temp_round - temp_round)/(temp_round + 273.2))*100,2)
            print("The absolute difference in temperatures is " + str(intercomp_temps_abs) + "°C" + "\n " + 
                  "and the percent difference in Celsius is " + str(intercomp_temps_percent) + "%" + "\n " + 
                  "and the percent difference in Kelvin is " + str(intercomp_temps_kelvin) + "%")

            intercomp_baro_abs = round((intercomp_baro_round - baro_lat_lon),2)
            intercomp_baro_percent = round(((intercomp_baro_round - baro_lat_lon)/baro_lat_lon)*100,2)
            print("The absolute difference in pressures is " + str(intercomp_baro_abs) + "mmHg" + "\n " + 
                  "and the percent difference is " + str(intercomp_baro_percent) + "%")
            print()

            intercomp_question = "Would you like to go back and change your temperature or pressure? (y/n): "
            intercomp_input = get_input(intercomp_question)
            if (intercomp_input):
                  continue
            else:
                  intercomp_flag = False
      return (intercomp_baro_abs, intercomp_baro_percent, intercomp_temps_abs, intercomp_temps_percent)      


def main():
      program_flag = True
      while(program_flag):
            #find your lat and lon here:
            print("Find your lat and lon via this website, or another of your choice: ")
            print('https://www.latlong.net/')
            print()
            
            #run the pressure pull and convert function
            baro_lat_lon = pressure()

            #ask the user if they want to continue to a Ctp correction
            continue_to_ctp_question = "Would you like to do a Ctp factor for the pulled pressure? (y/n): "
            continue_to_ctp_input = get_input(continue_to_ctp_question)
            if(not continue_to_ctp_input):
                  break
            #else continue to run Ctp function
            else:
                  temp_round = ctp(baro_lat_lon)
            
            #ask the user if they want to continue to an intercomparison
            continue_to_inter_question = "Would you like to do an intercomparison for the pulled pressure and input temp? (y/n): "
            continue_to_inter_input = get_input(continue_to_inter_question)
            if((not continue_to_inter_input) or (not continue_to_ctp_input)):
                  break
            #else continue to intercomparison
            else:
                  intercomparison(baro_lat_lon, temp_round)
            
            #ask user if they want to rerun the program
            program_question = "Would you like to rerun the program? (y/n): "
            program_input = get_input(program_question)
            if (program_input):
                  continue
            else:
                  program_flag = False
                  print("Thank you for using BaroMe, powered by Penn! Goodbye and go well!")
                  print()

#comment out below main call if only calling the functions, not using this as a program
if __name__=="__main__":
      main()
#
#END OF PROGRAM