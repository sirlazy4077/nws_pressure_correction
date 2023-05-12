# nws_pressure_correction
Convert the local station pressure (found via coordinates passed by user) to altitude-adjusted pressure

Currently working only with centers in the USA, as this queries the NWS website for the given lat/lon,
both to get the pressure and to get the altitude at the lat/lon

TODO:
1) Figure out an international edition?
    (potentially use this website: https://www.wunderground.com/hourly/39.94,-75.15/date/2023-05-13) 
2) Make into a webapp for easy use by a clinic
