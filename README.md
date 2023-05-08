# nws_pressure_correction
Convert the local station pressure (found via coordinates passed by user) to altitude-adjusted pressure

Currently working only with centers in the USA, as this queries the NWS website for the given lat/lon,
both to get the pressure and to get the altitude at the lat/lon

TODO:
1) Figure out an international edition?
2) Make into a webapp for easy use by a clinic
