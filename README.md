# nws_pressure_correction
Convert the local station pressure (found via coordinates passed by user) to altitude-adjusted pressure

Currently working only with centers in the USA, as this queries the NWS website for the given lat/lon,
both to get the pressure and to get the altitude at the lat/lon
