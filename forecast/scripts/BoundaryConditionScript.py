import os, sys
import math
import re
import datetime
from com.rma.io import DssFileManagerImpl
from com.rma.model import Project

import hec.heclib.dss
import hec.heclib.util.HecTime as HecTime
import hec.io.TimeSeriesContainer as tscont
import hec.hecmath.TimeSeriesMath as tsmath
from hec.script import MessageBox, Constants

import usbr.wat.plugins.actionpanel.model.forecast as fc
sys.path.append(os.path.join(Project.getCurrentProject().getWorkspacePath(), "forecast", "scripts"))

import CVP_ops_tools as CVP
reload(CVP)

DEBUG = True

def build_BC_data_sets(AP_start_time, AP_end_time, BC_F_part, BC_output_DSS_filename, ops_file_name, DSS_map_filename,
		position_analysis_year=None,
		position_analysis_config_filename=None,
		met_F_part=None,
		met_output_DSS_filename=None,
		flow_pattern_config_filename=None,
		ops_import_F_part=None):
	"""Build meteorological, hydrologic, and water-temperature boundary data sets.

	Parameters
	----------
	AP_start_time : HecTime
		Start of the simulation-group run period.
	AP_end_time : HecTime
		End of the simulation-group run period.
	BC_F_part : str
		DSS F-part assigned to generated boundary-condition records.
	BC_output_DSS_filename : str
		DSS file receiving generated boundary-condition time series. Assumed
		relative to the study directory if not already absolute.
	ops_file_name : str
		CVP operations spreadsheet or CSV file used as operational input.
		Assumed relative to the study directory if not already absolute.
	DSS_map_filename : str
		File receiving the location, parameter, DSS file, and pathname map.
		Assumed relative to the study directory if not already absolute.
	position_analysis_year : int, optional
		Historical source year used for meteorological positional analysis.
		Positional-analysis arguments remain necessary until another method
		for generating met data is implemented.
	position_analysis_config_filename : str, optional
		Configuration describing source meteorological DSS records. Assumed
		relative to the study directory. Defaults to
		forecast/config/historical_met.config.
	met_F_part : str, optional
		DSS F-part for meteorological records; defaults to ``BC_F_part``.
	met_output_DSS_filename : str, optional
		Separate meteorological DSS output file, if required. Assumed
		relative to the study directory. Defaults to ``BC_output_DSS_filename``.
	flow_pattern_config_filename : str, optional
		Configuration describing flow-pattern records used for disaggregation.
		Assumed relative to the study directory. Defaults to
		forecast/config/flow_pattern.config.
	ops_import_F_part : str, optional
		Label applied to records imported from the operations input file.

	Returns
	-------
	int
		Number of meteorological and operational map records generated, or 0
		when operational boundary-condition generation fails.

	Raises
	------
	ValueError
		If the operations-spreadsheet profile date does not match the
		analysis-window start date.

	Notes
	-----
	Relative paths are resolved against the current project workspace. The
	routine writes DSS records and a location/path mapping file as side
	effects. This function enforces that the operations-spreadsheet profile
	date matches the analysis-window start date; a mismatch raises
	ValueError rather than silently using an inconsistent date.
	"""

	# Resolve project-relative files and establish defaults for optional DSS
	# metadata and configuration inputs.
	if not os.path.isabs(BC_output_DSS_filename):
		BC_output_DSS_filename = os.path.join(Project.getCurrentProject().getWorkspacePath(), BC_output_DSS_filename)
	if not os.path.isabs(ops_file_name):
		ops_file_name = os.path.join(Project.getCurrentProject().getWorkspacePath(), ops_file_name)
	if not met_F_part:
		met_F_part = BC_F_part
	if not ops_import_F_part:
		ops_import_F_part = os.path.basename(ops_file_name)
	if not met_output_DSS_filename:
		met_output_DSS_filename=BC_output_DSS_filename
	elif not os.path.isabs(met_output_DSS_filename):
		met_output_DSS_filename = os.path.join(Project.getCurrentProject().getWorkspacePath(), met_output_DSS_filename)
	if not position_analysis_config_filename:
		position_analysis_config_filename = fc.ForecastConfigFiles.getHistoricalMetFile()
	elif not os.path.isabs(position_analysis_config_filename):
		position_analysis_config_filename = os.path.join(Project.getCurrentProject().getWorkspacePath(), position_analysis_config_filename)
	if not flow_pattern_config_filename:
		flow_pattern_config_filename = fc.ForecastConfigFiles.getFlowPatternFile()
	elif not os.path.isabs(flow_pattern_config_filename):
		flow_pattern_config_filename = os.path.join(Project.getCurrentProject().getWorkspacePath(), flow_pattern_config_filename)
	if not os.path.isabs(DSS_map_filename):
		DSS_map_filename = os.path.join(Project.getCurrentProject().getWorkspacePath(), DSS_map_filename)

	# Report the principal processing inputs and output destinations.
	print "\n########"
	print "\tGenerating Boundary Conditions for American River models"
	print "########\n"

	print "CVP Ops Data file: %s"%ops_file_name
	print "Met data config file: %s"%position_analysis_config_filename
	print "Flow pattern config file: %s"%flow_pattern_config_filename
	print "Boundary Condition output DSS file: %s"%BC_output_DSS_filename
	print "Met data output DSS file: %s"%met_output_DSS_filename
	print "Location/Path map file: %s"%DSS_map_filename
	
	### Prepare the operations data ###
	print("\nPreparing Operations Data...")
	
	# Read the operations file
	ops_dict = read_ops_bc_data(ops_file_name)
	
	# Extract the profile date from the operations
	profile_date = get_profile_date(ops_dict)
	
	### Handle date inconsistencies ###
	# It is currently possible to have an analysis window start date that's different from the profile and operations date specified in the operations sheet.
	# When this happens, the boundary condition information will incorrectly utilize the analysis window time rather than the profile/ops time. The results put
	# into the dss files will appear to be correct with the start date, but they are not calculated correctly for those dates. Forcing the boundary condition 
	# start date to use the profile date keeps everything aligned when calculating the time series. If the profile date and the analysis window dates are not 
	# the same, an error is thrown to force users to adjust the setup.
	
	# Convert the string to a date object
	profile_date_obj = datetime.datetime.strptime(profile_date, "%d%b%Y").date()
	ap_start_time_obj = datetime.datetime.strptime(AP_start_time.date(), '%d %B %Y').date()
	
	print('profile date', profile_date_obj)
	print('start time', ap_start_time_obj)
	if profile_date_obj < ap_start_time_obj:
		# Profile date is before the analysis date. Log to the console and throw an error.
		print('Starting operations date is before the analysis window date. This is an invalid configuration. Please adjust the analysis window start date ' + \
			  'to be ' + profile_date_obj.strftime('%m/%d/%Y'))
			  
		raise ValueError, "The profile date is before the analysis window date. Update the analysis window date to " + profile_date_obj.strftime('%m/%d/%Y')
		
	elif profile_date_obj > ap_start_time_obj:
		print('Starting operations date is after the analysis window date. This is an invalid configuration. Please adjust the analysis window start date ' + \
			  'to be ' + profile_date_obj.strftime('%m/%d/%Y'))
			  
		raise ValueError, "The profile date is after the analysis window date. Update the analysis window date to " + profile_date_obj.strftime('%m/%d/%Y')

	### Prepare the meteorlogic data ###
	print("\nPreparing Meteorological Data...")

	# Create the meteorlogic time series
	met_lines = create_positional_analysis_met_data(AP_start_time.year(), position_analysis_year, AP_start_time, AP_end_time,
		position_analysis_config_filename, met_output_DSS_filename, met_F_part)
	
	# Write the DSS path information to the path mapping file
	with open(os.path.join(Project.getCurrentProject().getWorkspacePath(), DSS_map_filename), "w") as mapfile:
		mapfile.write("location,parameter,dss file,dss path\n")
		for line in met_lines:
			mapfile.write(line + '\n')
			if DEBUG: print(line)

	print("Met process complete.\n")
	
	### Prepare the boundary condition data ###
	print("\nPreparing hydro and WC boundary conditions...")

	# Create the boundary condition timeseries
	ops_lines = create_ops_BC_data(ops_dict, profile_date, AP_start_time, AP_end_time,
		BC_output_DSS_filename, BC_F_part, ops_import_F_part, flow_pattern_config_filename, DSS_map_filename)
	
	# Return a placeholder value if the boundary condition generation failed
	if not ops_lines:
		return 0

	# Write the DSS path information to the path mapping file
	with open(os.path.join(Project.getCurrentProject().getWorkspacePath(), DSS_map_filename), "a") as mapfile:
		for line in ops_lines:
			mapfile.write(line)
			mapfile.write('\n')
	
	print "\nBoundary condition report written to: %s\n"%(DSS_map_filename)

	### Return the total number of generated time series ###
	return len(met_lines) + len(ops_lines)


def create_positional_analysis_met_data(target_year, source_year, start_time, end_time,
position_analysis_config_filename, met_output_DSS_filename, met_F_part):
	"""Shift historical meteorological data into a target analysis year.

	This is a simple time-shifter for meteorological positional-analysis data.
	Location-specific information and DSS file/path combinations are supplied
	through the positional-analysis configuration file rather than being
	hard-coded in this function.

	Parameters
	----------
	target_year : int
		Year to which the meteorological sequence is shifted.
	source_year : int
		Historical year supplying the meteorological sequence.
	start_time : HecTime
		Start of the target analysis period.
	end_time : HecTime
		End of the target analysis period.
	position_analysis_config_filename : str
		Configuration describing source and destination DSS records.
	met_output_DSS_filename : str
		DSS file receiving the shifted meteorological records.
	met_F_part : str
		DSS F-part assigned to shifted records.

	Returns
	-------
	list of str
		CSV-formatted mapping records for the generated meteorological series.

	Notes
	-----
	The source and generated series are assumed to have compatible time steps.
	"""
	print "Calculating positional met data..."
	print "Historical Met File: %s"%(fc.ForecastConfigFiles.getHistoricalMetFile())
	print "Position Analysis Met File: %s"%position_analysis_config_filename
	diff_years = target_year - source_year
	print "Shifting met data from %d to %d (%d years)."%(source_year, target_year, diff_years)

	rv_lines = []
	met_config_str = ""
	print "Met output DSS file: %s"%(met_output_DSS_filename)
	met_config_lines = getConfigLines(position_analysis_config_filename)

	# Process each configured meteorological source/destination mapping after
	# the configuration header.
	for line in met_config_lines[1:]:
		token = line.strip().split(',')
		dest_count = 0
		try:
			dest_count = int(token[4])
		except:
			print "File %s line \n\t \"%s\"\nis not a valid ID for a position analysis DSS record."%(position_analysis_config_filename,line)
			print "Can't read an integer value from \"%s\"."%(token[4])
			continue

		# Validate the expected number of fields given the configured
		# destination count before indexing further into the line.
		target_line_length = 5 + 2*dest_count
		if len(token) != target_line_length:
			print "File %s line \n\t \"%s\"\nis not a valid ID for a position analysis DSS record."%(position_analysis_config_filename,line)
			continue
		#source_DSS_file_name = os.path.join(Project.getCurrentProject().getWorkspacePath(), token[0].strip('\\'))
		source_DSS_file_name = os.path.join(Project.getCurrentProject().getWorkspacePath(), token[2].strip().strip('\\'))
		ts_read = hec.heclib.dss.HecTimeSeries()
		ts_read.setDSSFileName(source_DSS_file_name)
		if DEBUG: print "Reading %s from DSS file %s."%(token[3].strip(), source_DSS_file_name)

		# Reconstruct source and destination DSS paths, intentionally leaving
		# the D-part (index 3) blank between the doubled separators.
		source_path_parts = token[3].strip().strip('/').split('/', 5)
		dest_path_parts = token[6].strip().strip('/').split('/', 5)
		source_path = dest_path = '/'
		for index in (0,1,2,4,5):
			source_path += (source_path_parts[index] + '/')
			dest_path += (dest_path_parts[index] + '/')
			if index == 2:
				source_path += '/'
				dest_path += '/'

		# Read the historical source series identified by the reconstructed path.
		tsc_source = tscont()
		tsc_source.fullName = source_path
		status = ts_read.read(tsc_source, False)
		if status < 0:
			print "Failed to read meteorologic time series %s \n\tfrom DSS file %s"%(source_path, source_DSS_file_name)
			ts_read.done()
			continue
		tsmath_source = tsmath(tsc_source)
		time_step_label = token[3].strip().split('/')[5]
		if DEBUG:  print "\tTime series contains %d values."%(tsmath_source.getContainer().numberValues)
		if DEBUG:  print "\tShifting time series with shiftInTime(%s)."%("%dMo"%(diff_years*12))
		# tsmath_shift = tsmath_source.shiftInTime("%dYrar"%(diff_years))

		# Build the target time grid with one day of end padding, then locate
		# the corresponding start position back in the historical source year.
		padded_end_time = HecTime()
		padded_end_time.set(end_time.value() + 1440)
		tsmath_shift = tsmath.generateRegularIntervalTimeSeries(
			"%s 0000"%(start_time.date(4)),
			"%s 2400"%(padded_end_time.date(4)),
			time_step_label, "0M", 1.0)
		time_seek = HecTime(tsmath_shift.firstValidDate(), HecTime.MINUTE_INCREMENT)
		time_seek.setYearMonthDay(time_seek.year() - diff_years, time_seek.month(), time_seek.day(), time_seek.minutesSinceMidnight())

		# Abort this positional-analysis operation if the requested shifted
		# period begins before the available historical record.
		if time_seek.getMinutes() < tsmath_source.firstValidDate():
			print "Met position time shift out of range at source start..."
			return ['']
		source_container = tsmath_source.getContainer()
		shift_container = tsmath_shift.getContainer()
		start_index = 0

		# Find the first historical value corresponding to the shifted target
		# start time.
		for i in range(source_container.numberValues):
			if source_container.times[i] >= time_seek.getMinutes():
				start_index = i
				break
		if start_index == 0:
			print "Met position time shift out of range at source end..."
			return ['']
		# if this works, it's only because the source and shift TSCs have the same time step.
		for i in range(shift_container.numberValues):
			shift_container.values[i] = source_container.values[start_index + i]

		# Verify that the generated container retains the expected number of
		# values after copying the historical sequence.
		if len(shift_container.values) != shift_container.numberValues:
			print "You doofus!\nlen(values)=%d\nnumberValues=%d\n"%(len(shift_container.values), shift_container.numberValues)
			return ['']

		# Preserve source units/type and assign the destination DSS pathname
		# metadata before writing the shifted record.
		tsmath_shift.setType(tsmath_source.getType())
		tsmath_shift.setUnits(tsmath_source.getUnits())
		tsmath_shift.setPathname(dest_path)
		tsmath_shift.setVersion(met_F_part)
		ts_write = hec.heclib.dss.HecTimeSeries()
		ts_write.setDSSFileName(met_output_DSS_filename)
		if DEBUG: print "Writing %s to DSS file %s."%(shift_container.fullName, met_output_DSS_filename)
		ts_write.write(tsmath_shift.getData())
		ts_write.done()
		ts_read.done()

		#met_loc, met_param = token[1].strip().split('<', 1)
		met_loc = token[0]
		met_param = token[1]
		rv_lines.append("%s,%s,%s,%s"%(met_loc.strip(), met_param.strip().strip('>'),
		Project.getCurrentProject().getRelativePath(met_output_DSS_filename),
		tsmath_shift.getContainer().fullName))

	return rv_lines


def shift_daily_averages(source_tsm, AP_start_time, AP_end_time):
	"""Repeat a daily-average source pattern over the requested analysis period.

	Aligns the source pattern to the target period by matching day-of-year.

	Parameters
	----------
	source_tsm : TimeSeriesMath
		Source daily-average time series used as the repeating pattern.
	AP_start_time : HecTime
		Start of the requested analysis period.
	AP_end_time : HecTime
		End of the requested analysis period.

	Returns
	-------
	TimeSeriesMath
		Daily time series spanning the requested period.

	Notes
	-----
	The source data are assumed to span at least one full year so that the
	day-of-year seek below is guaranteed to find a match, and so indexing can
	wrap from the end of the source sequence back to its beginning.
	"""
	
	# copy start and end time so manipulations in this scope don't affect others
	shifted_start_time = HecTime()
	shifted_start_time.set(AP_start_time)
	shifted_end_time = HecTime()
	shifted_end_time.set(AP_end_time)

	# generate a time series that spans the target time; initialize appropriately
	rv_tsmath = tsmath.generateRegularIntervalTimeSeries(shifted_start_time.date(8), shifted_end_time.date(8), "1DAY", 1.0)
	rv_tsmath.setUnits(source_tsm.getUnits())
	rv_tsmath.setType(source_tsm.getType())
	rv_tsmath.setLocation(source_tsm.getContainer().location)
	rv_tsmath.setParameterPart(source_tsm.getContainer().parameter)

	# find the starting day in the source time series()
	seek_index = 0
	seek_time = HecTime()
	seek_time.set(source_tsm.getContainer().times[seek_index])
	print('seek_index:',seek_index,seek_time.dayOfYear(),shifted_start_time.dayOfYear())
	while seek_time.dayOfYear() != shifted_start_time.dayOfYear():  # caution, this assumes that a full year, or more is availabe in the source_tesm
		print('seek_index:',seek_index,seek_time.dayOfYear(),shifted_start_time.dayOfYear())
		seek_index += 1
		seek_time.set(source_tsm.getContainer().times[seek_index])

	# copy values from the source to the destination
	dest_index = 0
	while dest_index < rv_tsmath.getContainer().numberValues:
		rv_tsmath.getContainer().values[dest_index] = source_tsm.getContainer().values[seek_index]
		dest_index += 1
		seek_index += 1
		# wrap around to the beginning of the source when you hit the end
		# note that this presumes that the source data set spans whole years
		if seek_index >= source_tsm.getContainer().numberValues: seek_index = 0

	#return the time-series math object
	return rv_tsmath


def shift_monthly_averages(source_tsm, AP_start_time, AP_end_time):
	"""Repeat a monthly-average source pattern over the requested analysis period.

	Parameters
	----------
	source_tsm : TimeSeriesMath
		Source monthly-average time series used as the repeating pattern.
	AP_start_time : HecTime
		Start of the requested analysis period.
	AP_end_time : HecTime
		End of the requested analysis period.

	Returns
	-------
	TimeSeriesMath
		Monthly time series spanning the requested period.

	Notes
	-----
	The source data are expected to span complete years so indexing can wrap
	from the end of the source sequence back to its beginning.
	"""

	# copy start and end time so manipulations in this scope don't affect others
	shifted_start_time = HecTime()
	shifted_start_time.set(AP_start_time)
	shifted_end_time = HecTime()
	shifted_end_time.set(AP_end_time)

	# move start and end times to end of month
	for hec_time in (shifted_start_time, shifted_end_time):
		hec_time.setTime("2400")
		hec_time.addDays(CVP.get_days_in_month(hec_time.month(),hec_time.year()) - hec_time.day())

	# generate a time series that spans the target time; initialize appropriately
	rv_tsmath = tsmath.generateRegularIntervalTimeSeries(shifted_start_time.date(8), shifted_end_time.date(8), "1MON", 1.0)
	rv_tsmath.setUnits(source_tsm.getUnits())
	rv_tsmath.setType(source_tsm.getType())
	rv_tsmath.setLocation(source_tsm.getContainer().location)
	rv_tsmath.setParameterPart(source_tsm.getContainer().parameter)

	# find the starting month in the source time series()
	seek_index = 0
	seek_time = HecTime()
	seek_time.set(source_tsm.getContainer().times[seek_index])
	while seek_time.month() < shifted_start_time.month():
		seek_index += 1
		seek_time.set(source_tsm.getContainer().times[seek_index])

	# copy values from the source to the destination
	dest_index = 0
	while dest_index < rv_tsmath.getContainer().numberValues:
		rv_tsmath.getContainer().values[dest_index] = source_tsm.getContainer().values[seek_index]
		dest_index += 1
		seek_index += 1
		# wrap around to the beginning of the source when you hit the end
		# note that this presumes that the source data set spans whole years
		if seek_index >= source_tsm.getContainer().numberValues: seek_index = 0

	#return the time-series math object
	return rv_tsmath

def getConfigLines(fileName):
	"""Read a configuration file and strip supported comment syntax.

	Parameters
	----------
	fileName : str
		Path to the configuration file.

	Returns
	-------
	list of str
		Non-comment configuration content split into individual lines.
	"""
	commentRE = re.compile(r"<!--.*?-->", re.S)
	hashCommentRE = re.compile(r"#.*")
	with open(fileName) as infile:
		config_str = infile.read()
	config_str = commentRE.sub("", config_str)
	config_str = hashCommentRE.sub("", config_str).strip()
	config_str = re.sub(r"\n+", "\n", config_str)
	return  config_str.split('\n')

def interpolate_coeffs(year, month, day, coeff_dict):
	"""Interpolate monthly regression coefficients to a specific day.

	Uses linear interpolation between mid-month reference points.

	Parameters
	----------
	year : int
		Calendar year of the target date.
	month : int
		Calendar month (1-12) of the target date.
	day : int
		Calendar day of the target date.
	coeff_dict : dict of int -> list of float
		Regression coefficients keyed by month number (1-12).

	Returns
	-------
	list of float
		Coefficients linearly interpolated between the two neighboring
		mid-month reference points that bracket the (shifted) target day.

	Notes
	-----
	The input date is shifted back by one day before interpolation (see the
	offsetdate calculation), so the returned coefficients correspond to the
	day prior to the (year, month, day) supplied by the caller. This appears
	to be an intentional one-day lag convention rather than an off-by-one
	defect, but it is preserved exactly rather than corrected.
	"""
	indate = datetime.date(year,month,day)
	offsetdate = datetime.date.fromordinal(indate.toordinal() -1 )
	day = offsetdate.day
	month = offsetdate.month
	year = offsetdate.year
	last_month = month - 1
	next_month = month + 1
	if last_month == 0: last_month = 12
	if next_month == 13: next_month = 1
	last_month_middle = CVP.get_days_in_month(last_month, year)/2
	month_middle = CVP.get_days_in_month(month, year)/2
	next_month_middle = CVP.get_days_in_month(next_month, year)/2
	rv = []
	for i in range(len(coeff_dict[month])):
		# Interpolate forward toward next month's midpoint coefficient after
		# the current month's midpoint, otherwise interpolate backward from
		# last month's midpoint coefficient.
		if day > month_middle:
			denom = month_middle + next_month_middle
			num = day - month_middle
			val_interp = (coeff_dict[month])[i] + ((coeff_dict[next_month])[i]-(coeff_dict[month])[i])*num/denom
		else:
			denom = month_middle + last_month_middle
			num = day + last_month_middle
			val_interp = (coeff_dict[last_month])[i] + ((coeff_dict[month])[i]-(coeff_dict[last_month])[i])*num/denom
		rv.append(val_interp)
	return rv

def american_NF_temp(year, month, day, NF_cms, MF_cms, T_air):
	"""Estimate North Fork American River water temperature upstream of Folsom.

	CARDNO/Stantec regression. Coefficients are interpolated by day-of-year
	using interpolate_coeffs before being applied to the log-flow and
	air-temperature terms below.

	Parameters
	----------
	year : int
		Calendar year associated with the flow and air-temperature inputs.
	month : int
		Calendar month (1-12) associated with the inputs.
	day : int
		Calendar day associated with the inputs.
	NF_cms : float
		North Fork flow, cubic meters per second.
	MF_cms : float
		Middle Fork flow, cubic meters per second.
	T_air : float
		Air temperature, degrees C.

	Returns
	-------
	float
		Estimated water temperature, degrees C, or Constants.UNDEFINED when
		the regression result falls outside a plausible +/-100 degC range.
	"""
	NF_coeff = {
		1: [3.77355345,1.266462973,-0.123190654,0.208855328],
		2: [5.01269425,2.088352067,-2.308137666,0.289497256],
		3: [7.567546775,3.041537494,-4.644044856,0.336475774],
		4: [13.92872175,1.492628831,-5.956415444,0.277586609],
		5: [19.23009253,-4.149129915,-2.651244411,0.278923758],
		6: [22.00833065,-2.189707188,-4.319810831,0.181642599],
		7: [27.48138246,0.461104188,-8.105548108,0.071214161],
		8: [26.07638886,-0.055669605,-7.755782225,0.064216078],
		9: [19.87566754,-2.333806319,-4.285212562,0.10655613],
		10: [11.46335394,0.665477033,-2.908680136,0.35502391],
		11: [7.827069439,0.684950286,-1.34200308,0.367479789],
		12: [3.518780588,-0.273754836,1.585551206,0.295922482]
	}
	coeff = interpolate_coeffs(year, month, day, NF_coeff)
	# coeff = NF_coeff[month]
	rv = coeff[0] + coeff[1] * math.log10(NF_cms) + coeff[2] * math.log10(MF_cms) + coeff[3] * T_air
	if DEBUG:
		# message = "Coefficients %d %d %d: "%(year, month, day)
		# for c in coeff:
		# 	message += " %f,"%(c)
		# print message
		message2 = "Terms %d %d %d: %f + %f + %f + %f = %f "%(year, month, day, coeff[0], 
			coeff[1] * math.log10(NF_cms), coeff[2] * math.log10(MF_cms), coeff[3] * T_air, rv)
		print message2

	# Treat clearly non-physical regression outputs as undefined rather than
	# propagating them downstream.
	if rv > 100 or rv < -100:
		return Constants.UNDEFINED
	return rv

def american_SF_temp(year, month, day, SF_cms, T_air):
	"""Estimate South Fork American River water temperature upstream of Folsom.

	CARDNO/Stantec regression, structurally identical in approach to
	american_NF_temp but without a Middle Fork flow term.

	Parameters
	----------
	year : int
		Calendar year associated with the flow and air-temperature inputs.
	month : int
		Calendar month (1-12) associated with the inputs.
	day : int
		Calendar day associated with the inputs.
	SF_cms : float
		South Fork flow, cubic meters per second.
	T_air : float
		Air temperature, degrees C.

	Returns
	-------
	float
		Estimated water temperature, degrees C, or Constants.UNDEFINED when
		the regression result falls outside a plausible +/-100 degC range.
	"""
	SF_coeff = {
		1: [1.956291062,1.374298257,0.290009169],
		2: [3.893887348,0.220653927,0.282395021],
		3: [8.455829345,-1.422109321,0.224161329],
		4: [12.60480855,-3.050192978,0.222675413],
		5: [19.37361716,-5.815240399,0.204001471],
		6: [22.03004985,-6.605451819,0.215552251],
		7: [23.60375618,-5.62310084,0.113589656],
		8: [21.76127614,-5.196031305,0.105051348],
		9: [17.66271131,-4.067412751,0.154994985],
		10: [11.83159793,-2.665405159,0.299236849],
		11: [6.520659335,-0.366300723,0.373983078],
		12: [3.430491736,0.754616666,0.358139071]
	}
	coeff = interpolate_coeffs(year, month, day, SF_coeff)
	if DEBUG:
		message = "Coefficients %d %d %d: "%(year, month, day)
		for c in coeff:
			message += " %f,"%(c)
		print message
	rv = coeff[0] + coeff[1] * math.log10(SF_cms) + coeff[2] * T_air

	# Treat clearly non-physical regression outputs as undefined rather than
	# propagating them downstream.
	if rv > 100 or rv < -100:
		return Constants.UNDEFINED
	return rv

def american_SC_temp(month):
	"""Look up the South Canal monthly average inflow temperature into Folsom.

	CARDNO/Stantec monthly-average estimate; this is a fixed climatological
	value by month rather than a flow/air-temperature regression.

	Parameters
	----------
	month : int
		Calendar month (1-12).

	Returns
	-------
	float
		Estimated water temperature, degrees C, converted from the hard-coded
		Fahrenheit table below.
	"""
	SC_ave_temp = {
		1: 46.02,
		2: 46.48,
		3: 48.94,
		4: 49.83,
		5: 52.32,
		6: 55.61,
		7: 59.43,
		8: 63.05,
		9: 64.82,
		10: 60.24,
		11: 53.48,
		12: 48.53
	}
	return (SC_ave_temp[month] -32.0)*5.0/9.0
    
def read_ops_bc_data(ops_file_name):
	"""Read and parse the forecast operations file.

	Detects the file format from its extension; if the extension indicates
	Excel, the spreadsheet parser is used, otherwise the file is assumed to
	be comma-separated. The resulting object is returned to the calling
	function without modification.

	Parameters
	----------
	ops_file_name : str
		Path to the operations file being used for the analysis.

	Returns
	-------
	dict
		Contents of the operations spreadsheet for later use, or ``None``
		if the file could not be read.
	"""

	# Define the locations that are in the sheet
	forecast_locations = ["Trinity/Clair Engle", "Whiskeytown", "Shasta", "Oroville", "Folsom", "New Melones", " SAN LUIS/O'NEILL", "DELTA"]
	
	# Define the active location
	active_locations = ["Folsom"]

	# Attempt to read the operations file, otherwise return none to signify missing data
	try:
		if ops_file_name.endswith(".xls") or ops_file_name.endswith(".xlsx"):
			# Read the spreadsheet
			ops_data = CVP.import_CVP_Ops_xls(ops_file_name, forecast_locations, active_locations)
		
		else:
			# Assume that the forecast is in CSV format and parse the data
			ops_data = CVP.import_CVP_Ops_csv(ops_file_name, forecast_locations, active_locations)
	
	except Exception as e:
		# Catch all exceptions. Read failed. Log and return None to indicate a failure
		print "Failed to read operations file:%s"%ops_file_name
		print "\t%s"%str(e)
		ops_data = None

	# Return to the calling function
	return ops_data
	
	
def get_profile_date(ops_data):
	"""Extract the profile date from the operations dictionary.

	The profile-date metadata row is deleted from ``ops_data`` once found, so
	the profile date returned here must be passed explicitly to downstream
	functions that need it.

	Parameters
	----------
	ops_data : dict
		Contents of the operations spreadsheet, as returned by
		read_ops_bc_data. Modified in place to remove the profile-date row.

	Returns
	-------
	str or None
		Date of the profile from the operations spreadsheet in the internal
		system format monthdayyear as numbers without spaces, or ``None`` if
		no profile date was found or it could not be parsed.
	"""
	
	# Set a placeholder for the profile date.
	profile_date = None

	# Parse the ops sheet to find the profile date value. Loop over the dictionary to find the key
	for key in ops_data.keys():
		# Print additional information if in debug mode
		if DEBUG:
			print "ops_data key: %s"%(key)
		
		# Attempt to find the profile date
		if ops_data[key][1].strip().upper().startswith("PROFILEDATE"):
			# Profile date has been found. Split it out for later use.
			profile_date = ops_data[key][1].split(':')[1].strip()
			
			# Delete the key from the dictionary
			del ops_data[key][1]

	# If a valid profile date has been found, parse it from the input string into a standard date string
	if profile_date:
		# Attempt to convert the string
		try:
			# Attempt to parse, splitting on a dash
			date_parts = profile_date.split('-', 2)
			
			# Check that the format of th
			if len(date_parts[2]) < 4: 
				date_parts[2] = "20" + date_parts[2]
			
			# Convert the string into a standard date format, monthdayyear
			profile_date = "%s%s%s"%(date_parts[0],date_parts[1],date_parts[2])
		
		except Exception as e:
			# Catch all exceptions. The parse failed, meaning the string was li
			print "Failed to read profile date from string:%s"%profile_date
			print "\t%s"%str(e)
			
			# Set the profile date as none to signify a parse failure
			return None
		
		print "Profile date: %s"%profile_date
		
	# Return to the calling function
	return profile_date
	
	

def create_ops_BC_data(ops_data, profile_date, start_time, end_time, BC_output_DSS_filename,
	BC_F_part, ops_import_F_part, flow_pattern_config_filename, DSS_map_filename):
	"""Process the CVP operations spreadsheet into Folsom-area boundary conditions.

	Disaggregates monthly Folsom operations data to daily/hourly flow,
	constructs a Folsom reservoir water balance, splits Folsom inflow into
	North/South Fork (and further into North Fork/Middle Fork) tributary
	flows, estimates tributary water temperatures via regression, generates
	municipal withdrawal time series from monthly patterns, and writes the
	resulting time series to DSS.

	Parameters
	----------
	ops_data : dict
		Parsed operations-spreadsheet contents, keyed by location, with the
		profile-date metadata row already removed by get_profile_date.
	profile_date : str or None
		Operations-sheet profile date in compact monthdayyear form, or None.
	start_time : HecTime
		Start of the forecast time window.
	end_time : HecTime
		End of the forecast time window.
	BC_output_DSS_filename : str
		DSS file receiving generated boundary-condition records.
	BC_F_part : str
		DSS F-part assigned to generated records.
	ops_import_F_part : str
		Version label associated with imported operations data.
	flow_pattern_config_filename : str
		Configuration identifying flow-pattern DSS records for municipal
		withdrawal disaggregation.
	DSS_map_filename : str
		Location/path map containing meteorological DSS references.

	Returns
	-------
	list of str or None
		CSV-formatted map records for generated DSS time series, or ``None``
		when required configuration cannot be resolved.

	Notes
	-----
	Unlike the Sacramento/Trinity boundary-condition script, this version
	reads ops_data/profile_date directly as arguments rather than re-reading
	the ops file itself, and the per-reservoir pattern-based (weighted)
	disaggregation block for Folsom inflow is present in source but disabled
	(see the block comment preserved below); uniform disaggregation is used
	in its place.
	"""
	print "  Forecast time window start: %s"%(start_time.dateAndTime(4))
	print "  Forecast time window end: %s"%(end_time.dateAndTime(4))

	rv_lines = []

	# Read the Folsom calendar metadata that establishes the starting column
	# and month for monthly values in the operations spreadsheet.
	folsom_tsc_list = []
	folsom_calendar = ops_data["Folsom"][0].split(',')
	start_index = int(folsom_calendar[0])
	start_month = folsom_calendar[start_index + 1].strip().upper()
	if DEBUG: print "\n Folsom start month: %s; Start index: %d"%(start_month, start_index)

	# Establish the operations start date and, when a profile date is
	# present, the number of days represented by the partial first month.
	ops_start_date = HecTime()
	days_in_first_month = None
	if profile_date:
		ops_start_date.set(profile_date, "2400")
		days_in_first_month = 1 + CVP.get_days_in_month(CVP.month_index(start_month), ops_start_date.year()) - ops_start_date.day()
	else:
		ops_start_date.set("01%s%d"%(start_month, start_time.year()), "0000")
		if ops_start_date > start_time:
			ops_start_date.set("01%s%d"%(start_month, start_time.year()-1), "0000")

	# Convert each Folsom spreadsheet row into a monthly TimeSeriesContainer,
	# adjusting the starting month when a numeric value precedes the nominal
	# calendar start column.
	for line in ops_data["Folsom"][1:]:
		data_month = start_month
		data_year = ops_start_date.year()
		if len(line.split(',')[0]) ==0:
			continue
		if CVP.is_convertable_to_float(line.split(',')[start_index - 1].strip()):
			data_month = CVP.month_TLA[CVP.previous_month(CVP.month_index(start_month))]
			if data_month == "DEC":
				data_year -= 1
		if DEBUG: print "Start_index = %d\nData_Month = %s"%(start_index, data_month)
		if DEBUG: print "Passing line to CVP.make_ops_tsc: %s"%(line)
		folsom_tsc_list.append(CVP.make_ops_tsc("FOLSOM", data_year, data_month, line, ops_label=ops_import_F_part))
    

	'''
	Disabled code for temporal pattern
	To restore:
		1. Remove block comment here
		2. Find computation that creates tsmath_daily_flow and switch from uniform
			to weighted disaggregation of inflow volume
		3. Just above return statement for this function, restore ts_pattern.done()
	# We have one temporal flow pattern for the American River inflow to Folsom Lake.
	# The DSS record for that pattern is called "pattern_path" here. We'll need to be
	# more specific if we have patterns for more than one hydrograph. See SacTrinity BC
	# script for examples.

	pattern_DSS_file_name = ""
	pattern_path = ""
	flow_pattern_config_lines = getConfigLines(flow_pattern_config_filename)
	#print "Flow Pattern config file contents:"
	#for line in flow_pattern_config_lines: print "\t%s"%line
	for line in flow_pattern_config_lines:
		token = line.strip().split(',')
		if len(token) != 3:
			print "File %s line \n\t \"%s\"\nis not a valid ID for a flow pattern DSS record."%(flow_pattern_config_filename,line)
			continue
		if line.split(',')[0].strip().upper() == "FOLSOM":
			pattern_DSS_file_name = line.split(',')[1].strip().strip('\\')
			pattern_path = line.split(',')[2].strip()
	if len(pattern_DSS_file_name) == 0 or len(pattern_path) == 0:
		print "Error reading flow pattern configuration file\n\t%s"%(flow_pattern_config_filename)
		print "Folsom pattern DSS file or path not found."
		return None
	if not os.path.isabs(pattern_DSS_file_name):
		pattern_DSS_file_name = os.path.join(Project.getCurrentProject().getWorkspacePath(), pattern_DSS_file_name)
		# print "Flow pattern for Folsom in \n\t%s"%(pattern_DSS_file_name)
		# print "\t" + pattern_path

	ts_pattern = hec.heclib.dss.HecTimeSeries()
	ts_pattern.setDSSFileName(pattern_DSS_file_name)
	'''

	DSS_map_lines = getConfigLines(DSS_map_filename)
	#print "DSS map config file contents:"
	#for line in DSS_map_lines: print "\t%s"%line

	# Locate the Fair Oaks air-temperature record previously written to the
	# DSS map; it drives the Folsom tributary temperature regressions below.
	met_DSS_file_name = ""
	airtemp_path = ""
	for line in DSS_map_lines:
		if (line.split(',')[0].strip().upper() == "FAIR OAKS" and
			line.split(',')[1].strip().upper() == "AIR TEMPERATURE"):
			met_DSS_file_name = line.split(',')[2].strip().strip('\\')
			airtemp_path = line.split(',')[3].strip()
	if len(met_DSS_file_name) == 0 or len(airtemp_path) == 0:
		print "Error reading Fair Oaks air temperature data configuration from file\n\t%s"%(met_DSS_file_name)
		print "Air temperature DSS file or path not found."
		return None
	if not os.path.isabs(met_DSS_file_name):
		met_DSS_file_name = os.path.join(Project.getCurrentProject().getWorkspacePath(), met_DSS_file_name)

	########################
	# Folsom data from CVP spreadsheet
	########################

	# Initialize the daily accumulated-depletion series used to account for
	# Folsom evaporation (and any other net loss) within the reservoir
	# water balance below.
	tsmath_list = []
	print "TS Location = %s"%(folsom_tsc_list[0].location.upper())
	print "  Start date = %s"%(start_time.date(4))
	print "  End date = %s"%(end_time.date(4))
	tsmath_folsom_acc_dep = tsmath.generateRegularIntervalTimeSeries(
		"%s 0000"%(ops_start_date.date(4)),
		"%s 2400"%(end_time.date(4)),
		"1DAY", "0M", 0.0)
	tsmath_folsom_acc_dep.setUnits("CFS")
	tsmath_folsom_acc_dep.setType("PER-AVER")
	tsmath_folsom_acc_dep.setTimeInterval("1DAY")
	tsmath_folsom_acc_dep.setWatershed("AMERICAN RIVER")
	tsmath_folsom_acc_dep.setLocation("FOLSOM LAKE")
	tsmath_folsom_acc_dep.setParameterPart("FLOW-ACC-DEP")
	tsmath_folsom_acc_dep.setVersion(BC_F_part)

	# Interpret each imported Folsom series according to its parameter label
	# and construct the corresponding boundary-condition and water-balance
	# components. Uniform (not pattern-weighted) disaggregation is used
	# throughout, consistent with the disabled weighted-pattern block above.
	for ts in folsom_tsc_list:
		print "\tTS Parameter = %s"%(ts.parameter.upper())
		if ts.parameter.upper() == "INFLOW":
			tsmath_flow_monthly = tsmath(ts)
			tsmath_list.append(tsmath_flow_monthly)
			# print "reading pattern from file: " + pattern_DSS_file_name
			# print "\t" + pattern_path
			# tsc_pattern = tscont()
			# tsc_pattern.fullName = pattern_path
			# status = ts_pattern.read(tsc_pattern, False)
			# if status < 0:
				# print "Failed to read meteorologic time series %s \n\tfrom DSS file %s"%(source_path, source_DSS_file_name)
				# tsread.done()
				# continue
			# tsmath_pattern = tsmath(tsc_pattern)
			# tsmath_daily_flow = CVP.weight_transform_monthly_to_daily(tsmath(ts), tsmath_pattern, start_day_count=days_in_first_month)
			tsmath_daily_flow = CVP.uniform_transform_monthly_to_daily(tsmath(ts), start_day_count=days_in_first_month)
			tsmath_daily_flow.setPathname(ts.fullName)
			tsmath_daily_flow.setTimeInterval("1DAY")
			tsmath_daily_flow.setParameterPart("FLOW-IN")
			tsmath_daily_flow.setVersion(BC_F_part)
			tsmath_list.append(tsmath_daily_flow)
		elif ts.parameter.upper() == "EST. EVAP.":
			# Evaporation is subtracted from the daily accumulated-depletion
			# term but, unlike the Sac/Trinity script, is not separately
			# subtracted from a monthly volume-balance series here.
			tsmath_folsom_evap_monthly = tsmath(ts)
			tsmath_list.append(tsmath_folsom_evap_monthly)
			tsmath_folsom_acc_dep = tsmath_folsom_acc_dep.subtract(
				CVP.uniform_transform_monthly_to_daily(tsmath(ts), start_day_count=days_in_first_month))
		elif "STORAGE" in ts.parameter.upper():
			# Convert monthly storage to instantaneous storage and derive
			# successive storage changes used by the daily storage
			# integration below.
			tsmath_storage_monthly =  tsmath(ts)
			tsmath_storage_monthly.setParameterPart("STORAGE")
			tsmath_storage_monthly.setType("INST-CUM")
			tsm_storage_change = tsmath_storage_monthly.successiveDifferences()
			tsmath_storage_monthly.setType("INST-VAL")
			tsmath_list.append(tsmath_storage_monthly)
			tsm_storage_change.setWatershed("")
			tsm_storage_change.setLocation("FOLSOM LAKE")
			tsm_storage_change.setParameterPart("STORAGE-CHANGE")
			tsmath_list.append(tsm_storage_change)
		elif ts.parameter.upper() == "TOTAL RELEASE":
			# Convert total monthly Folsom release to an hourly release-flow
			# boundary condition while retaining the monthly volume record.
			tsmath_release_monthly = tsmath(ts)
			tsmath_list.append(tsmath_release_monthly)
			tsmath_release = CVP.uniform_transform_monthly_to_hourly(tsmath(ts), start_day_count=days_in_first_month)
			tsmath_release.setPathname(ts.fullName)
			tsmath_release.setTimeInterval("1HOUR")
			tsmath_release.setParameterPart("FLOW-RELEASE")
			tsmath_release.setVersion(BC_F_part)
			tsmath_list.append(tsmath_release)
		elif ts.parameter.upper() == "ACTUAL NIMBUS RELEASE (TAF)":
			# Nimbus releases are downstream of Folsom at Lake Natoma;
			# relocate the watershed/location metadata accordingly.
			tsmath_nimbus_monthly = tsmath(ts)
			tsmath_nimbus_monthly.setWatershed("AMERICAN RIVER")
			tsmath_nimbus_monthly.setLocation("LAKE NATOMA")
			tsmath_list.append(tsmath_nimbus_monthly)
			tsmath_nimbus = CVP.uniform_transform_monthly_to_daily(tsmath_nimbus_monthly, start_day_count=days_in_first_month)
			tsmath_nimbus.setPathname(ts.fullName)
			tsmath_nimbus.setWatershed("AMERICAN RIVER")
			tsmath_nimbus.setLocation("LAKE NATOMA")
			tsmath_nimbus.setParameterPart("FLOW-NIMBUS ACTUAL")
			tsmath_nimbus.setTimeInterval("1DAY")
			tsmath_nimbus.setVersion(BC_F_part)
			tsmath_list.append(tsmath_nimbus)
		elif ts.parameter.upper() == "FLOW-AMER AFRP":
			# Explicitly set units/type before wrapping in TimeSeriesMath,
			# since the source parameter name does not follow the standard
			# convention otherwise used to infer them.
			ts.units = "CFS"
			ts.type = "PER-AVER"
			tsmath_afrp_monthly = tsmath(ts)
			tsmath_list.append(tsmath_afrp_monthly)
			tsmath_afrp = CVP.uniform_transform_monthly_to_daily(tsmath(ts), start_day_count=days_in_first_month)
			tsmath_afrp.setPathname(ts.fullName)
			tsmath_afrp.getContainer().parameter = "FLOW-AFRP"
			tsmath_afrp.setTimeInterval("1DAY")
			tsmath_afrp.setVersion(BC_F_part)
			tsmath_list.append(tsmath_afrp)
		elif ts.parameter.upper() == "PUMPING (FP)":
			tsmath_fp_monthly = tsmath(ts)
			tsmath_list.append(tsmath_fp_monthly)
			tsmath_fp = CVP.uniform_transform_monthly_to_daily(tsmath(ts), start_day_count=days_in_first_month)
			tsmath_fp.setPathname(ts.fullName)
			tsmath_fp.getContainer().parameter = "FLOW-PUMPING"
			tsmath_fp.setTimeInterval("1DAY")
			tsmath_fp.setVersion(BC_F_part)
			tsmath_list.append(tsmath_fp)
		elif ts.parameter.upper() == "FS CANAL (FSC)":
			tsmath_fsc_monthly = tsmath(ts)
			tsmath_list.append(tsmath_fsc_monthly)
			tsmath_fsc = CVP.uniform_transform_monthly_to_daily(tsmath(ts), start_day_count=days_in_first_month)
			tsmath_fsc.setPathname(ts.fullName)
			tsmath_fsc.getContainer().parameter = "FLOW-FSC"
			tsmath_fsc.setTimeInterval("1DAY")
			tsmath_fsc.setVersion(BC_F_part)
			tsmath_list.append(tsmath_fsc)
		else:
			tsmath_list.append(tsmath(ts))

	# Folsom storage changes due to:
	#	In:
	#		Folsom inflow : tsmath_daily_flow
	#	Out:
	#		Folsom dam releases: tsmath_release_daily
	#		Net evaporation, leakage, other: tsmath_acc_dep

	# Construct a daily Folsom storage trajectory, using monthly storage
	# values as fixed checkpoints and the daily water balance between those
	# checkpoints. Note: unlike the storage-change series created above,
	# this reservoir balance uses tsmath_release_monthly (total release)
	# rather than a dedicated net-balance series, since Folsom has no
	# separate monthly volume-balance accumulator in this script.
	tsmath_storage_daily = tsmath.generateRegularIntervalTimeSeries(
		"%s 0000"%(ops_start_date.date(4)),
		"%s 2400"%(end_time.date(4)),
		"1DAY", "0M", 0.0)
	tsmath_storage_daily.setUnits("AC-FT")
	tsmath_storage_daily.setType("INST-VAL")
	tsmath_storage_daily.setTimeInterval("1DAY")
	tsmath_storage_daily.setWatershed("AMERICAN RIVER")
	tsmath_storage_daily.setLocation("FOLSOM LAKE")
	tsmath_storage_daily.setParameterPart("STORAGE-CVP")
	tsmath_storage_daily.setVersion(BC_F_part)
	tsmath_storage_daily.getContainer().values[0] = tsmath_storage_monthly.getContainer().values[0]
	tsmath_release_daily = CVP.uniform_transform_monthly_to_daily(
		tsmath_release_monthly, start_day_count=days_in_first_month)

	j = 1
	search_time = HecTime()

	# At each monthly checkpoint, reset to the imported storage value;
	# otherwise integrate the daily inflow, release, and accumulated-
	# depletion balance (1.98347 converts CFS-days to acre-feet).
	for i in range(1, len(tsmath_storage_daily.getContainer().values)):
		if tsmath_storage_daily.getContainer().times[i] >= tsmath_storage_monthly.getContainer().times[j]:
			tsmath_storage_daily.getContainer().values[i] = tsmath_storage_monthly.getContainer().values[j]
			j += 1
		else:
			search_time.set(tsmath_storage_daily.getContainer().times[i])
			tsmath_storage_daily.getContainer().values[i] = (
				tsmath_storage_daily.getContainer().values[i-1] + 1.98347*(
				tsmath_daily_flow.getContainer().getValue(search_time)
				- tsmath_release_daily.getContainer().getValue(search_time)
				+ tsmath_folsom_acc_dep.getContainer().getValue(search_time)))
	tsmath_list.append(tsmath_storage_daily)
	tsmath_list.append(tsmath_folsom_acc_dep)

	########################
	# Disaggregate Folsom Tributary In Flows
	########################

	# Split total Folsom inflow into North Fork and South Fork fractions by
	# month, then retain each generated series by location name for use in
	# the temperature regressions below.
	tributary_weights = {
		"Folsom-NF-in":(0.616122397481848, 0.634490648, 0.655322726, 0.614507479, 0.5324295713, 0.490282586,
						0.486906093, 0.469756669, 0.495028826, 0.388437959, 0.539534578, 0.609745525),
		"Folsom-SF-in":(0.383877603, 0.365509352, 0.344677274, 0.385492521, 0.467570429, 0.509717414,
						0.513093907, 0.530243331, 0.504971174, 0.611562041, 0.460465422, 0.390254475)}
	names_flows = {}
	for tsm in CVP.split_time_series_monthly(tsmath_daily_flow, tributary_weights, "FLOW-IN"):
		tsm.setVersion(BC_F_part)
		tsmath_list.append(tsm)
		names_flows[tsm.getContainer().location] = tsm

	# Further split North Fork flow into its North Fork (above Middle Fork
	# confluence) and Middle Fork (above North Fork confluence) components,
	# expressed as monthly fractions of total North Fork flow to Folsom.
	NF_tributary_weights ={
		"North Fork abv MF":(0.400374748, 0.451766344 , 0.492703683, 0.517924061, 0.506387691, 0.333514521,
							0.153097495, 0.08235269, 0.088692849, 0.221268985, 0.235921776, 0.332332904),
		"Middle Fork abv NF":(0.599625252, 0.548233656, 0.507296317, 0.482075939, 0.493612309, 0.666485479,
							0.846902505, 0.91764731, 0.911307151, 0.778731015, 0.764078224, 0.667667096)}
	for tsm in CVP.split_time_series_monthly(names_flows["Folsom-NF-in"], NF_tributary_weights, "FLOW-IN"):
		tsm.setVersion(BC_F_part)
		tsmath_list.append(tsm)
		names_flows[tsm.getContainer().location] = tsm

	########################
	# Get flows and temperatures for downstream tributaries, and other seasonal stuff
	# from monthly average data sets
	########################

	# Read each configured tributary-average record, detect whether it is
	# stored at a monthly or daily time step from its DSS pathname E-part,
	# and shift the repeating seasonal pattern onto the forecast period.
	tributary_config_filename = os.path.join(Project.getCurrentProject().getWorkspacePath(), r"forecast\config\tributary_averages.config")
	# trib_DSS_files = {}
	for line in getConfigLines(tributary_config_filename):
		token = line.split(',')
		dss_file_name = token[-2].strip()
		if not os.path.isabs(dss_file_name):
			dss_file_name = os.path.join(Project.getCurrentProject().getWorkspacePath(), dss_file_name)
		ts_read = hec.heclib.dss.HecTimeSeries()
		ts_read.setDSSFileName(dss_file_name)
		tsc_avg = tscont()
		tsc_avg.fullName = token[-1].strip()
		status = ts_read.read(tsc_avg, False)
		if status < 0:
			print "Failed to read temperature time series %s \n\tfrom DSS file %s"%(tsc_avg.fullName, dss_file_name)
			ts_read.done()
			continue
		tsmath_avg = tsmath(tsc_avg)
		shift_path = token[-1].strip().split('/')
		if shift_path[5] == '1MON':
			# Monthly-average source: shift to the forecast period, then
			# disaggregate uniformly to daily values.
			tsmath_shift = shift_monthly_averages(tsmath_avg, start_time, end_time)
			shift_path[6] = BC_F_part
			tsmath_shift.getContainer().fullName = '/'.join(shift_path)
			tsmath_list.append(CVP.uniform_transform_monthly_to_daily(tsmath_shift, start_day_count=days_in_first_month))
			ts_read.done()
		elif shift_path[5] == '1DAY':
			# Daily-average source: shift directly by day-of-year without
			# further disaggregation.
			tsmath_shift = shift_daily_averages(tsmath_avg, start_time, end_time)
			shift_path[6] = BC_F_part
			tsmath_shift.getContainer().fullName = '/'.join(shift_path)
			tsmath_list.append(tsmath_shift)
			ts_read.done()
		else:
			print "Failed to read temperature time series %s \n\tfrom DSS file %s"%(tsc_avg.fullName, dss_file_name)
			print "Only '1MON' and '1DAY' average records can be remapped."
			ts_read.done()
			continue

	########################
	# Estimate Folsom Tributary Temperatures
	########################
	std_out_restore = sys.stdout
	if DEBUG:
		print('Entering wonderland', os.path.join(Project.getCurrentProject().getWorkspacePath(), "AMR_temp_calc.log"))
		temperature_logfile = open(os.path.join(Project.getCurrentProject().getWorkspacePath(), "AMR_temp_calc.log"), 'w')

	# South Fork water temperature from regression formula

	# Ensure South Fork flow is in metric units (m^3/s) as required by the
	# american_SF_temp regression.
	if names_flows["Folsom-SF-in"].isMetric():
		tsmath_SF_cms = names_flows["Folsom-SF-in"]
	else:
		tsmath_SF_cms = names_flows["Folsom-SF-in"].convertToMetricUnits()

	# Read the Fair Oaks air-temperature series and convert it to metric
	# units and a daily average, both required by the regression functions.
	print "DSS file for Fair Oaks air temperature: " + met_DSS_file_name
	print "DSS path for Fair Oaks air temperature: : " + airtemp_path
	ts_read = hec.heclib.dss.HecTimeSeries()
	ts_read.setDSSFileName(met_DSS_file_name)
	tsc_airtemp = tscont()
	tsc_airtemp.fullName = airtemp_path
	status = ts_read.read(tsc_airtemp, False)
	if status < 0:
		print "Failed to read temperature time series %s \n\tfrom DSS file %s"%(airtemp_path, met_DSS_file_name)
		ts_read.done()
	tsmath_airtemp = tsmath(tsc_airtemp)
	ts_read.done()
	if tsmath_airtemp.isMetric():
		tsmath_T_air = tsmath_airtemp
	else:
		tsmath_T_air = tsmath_airtemp.convertToMetricUnits()
	tsmath_T_air_daily = tsmath_T_air.transformTimeSeries("1Day", "0M", "AVE")

	print "South Fork Temp start time = " + start_time.date(4) + ' ' + str(start_time.minutesSinceMidnight())
	print "South Fork Temp end time = " + end_time.date(4) + ' ' + str(end_time.minutesSinceMidnight())
    
	# Evaluate the South Fork regression day-by-day over the forecast period.
	tsmath_SF_WTemp = tsmath.generateRegularIntervalTimeSeries(start_time.dateAndTime(4), end_time.dateAndTime(4), "1DAY", "", 0.0)
	time_post = HecTime(HecTime.MINUTE_INCREMENT)
	i = 0
	SF = tsmath_SF_cms.getContainer()
	T = tsmath_T_air_daily.getContainer()
	for time_step in tsmath_SF_WTemp.getContainer().times:
		time_post.set(time_step)
		tsmath_SF_WTemp.getContainer().values[i] = american_SF_temp(time_post.year(),
					time_post.month(), time_post.day(),
					tsmath_SF_cms.getContainer().getValue(time_post),
					tsmath_T_air_daily.getContainer().getValue(time_post))
		if DEBUG and time_post.day() % 5 == 0:
			print "DT: %s (%d); SF flow: %.2f; Air Temp: %.2f; SF Water Temp: %.2f"%(
				time_post.dateAndTime(4), time_post.month(),
				tsmath_SF_cms.getContainer().getValue(time_post),
				tsmath_T_air_daily.getContainer().getValue(time_post),
				tsmath_SF_WTemp.getContainer().values[i])
		i += 1
        
	tsmath_SF_WTemp.setUnits("Deg C")
	tsmath_SF_WTemp.setType("PER-AVER")
	tsmath_SF_WTemp.setTimeInterval("1DAY")
	tsmath_SF_WTemp.setLocation("Folsom-SF-in")
	tsmath_SF_WTemp.setParameterPart("TEMP-WATER")
	tsmath_SF_WTemp.setVersion(BC_F_part)
	tsmath_list.append(tsmath_SF_WTemp)

	# North Fork water temperature from regression formula

	# Ensure North Fork and Middle Fork flows are in metric units as
	# required by the american_NF_temp regression.
	if names_flows["North Fork abv MF"].isMetric():
		tsmath_NF_cms = names_flows["North Fork abv MF"]
	else:
		tsmath_NF_cms = names_flows["North Fork abv MF"].convertToMetricUnits()
	if names_flows["Middle Fork abv NF"].isMetric():
		tsmath_MF_cms = names_flows["Middle Fork abv NF"]
	else:
		tsmath_MF_cms = names_flows["Middle Fork abv NF"].convertToMetricUnits()

	# Evaluate the North Fork regression day-by-day over the forecast period.
	tsmath_NF_WTemp = tsmath.generateRegularIntervalTimeSeries(start_time.dateAndTime(4), end_time.dateAndTime(4), "1DAY", "", 0.0)
	i = 0
	for time_step in tsmath_NF_WTemp.getContainer().times:
		time_post.set(time_step)
		tsmath_NF_WTemp.getContainer().values[i] = american_NF_temp(time_post.year(),
					time_post.month(), time_post.day(),
					tsmath_NF_cms.getContainer().getValue(time_post),
					tsmath_MF_cms.getContainer().getValue(time_post),
					tsmath_T_air_daily.getContainer().getValue(time_post))
		if DEBUG and time_post.day() % 5 == 0:
			print "DT: %s (%d); NF flow: %.2f; MF flow: %.2f; Air Temp: %.2f; NF Water Temp: %.2f"%(
				time_post.dateAndTime(4), time_post.month(),
				tsmath_NF_cms.getContainer().getValue(time_post),
				tsmath_MF_cms.getContainer().getValue(time_post),
				tsmath_T_air_daily.getContainer().getValue(time_post),
				tsmath_NF_WTemp.getContainer().values[i])
		i += 1
        
	tsmath_NF_WTemp.setUnits("Deg C")
	tsmath_NF_WTemp.setType("PER-AVER")
	tsmath_NF_WTemp.setTimeInterval("1DAY")
	tsmath_NF_WTemp.setLocation("Folsom-NF-in")
	tsmath_NF_WTemp.setParameterPart("TEMP-WATER")
	tsmath_NF_WTemp.setVersion(BC_F_part)
	tsmath_list.append(tsmath_NF_WTemp)

	# South Canal water temperature -- constant by month, no regression coefficients
	tsmath_SC_WTemp = tsmath.generateRegularIntervalTimeSeries(start_time.dateAndTime(4), end_time.dateAndTime(4), "1DAY", "", 0.0)
	i = 0
	for time_step in tsmath_SC_WTemp.getContainer().times:
		time_post.set(time_step)
		tsmath_SC_WTemp.getContainer().values[i] = american_SC_temp(time_post.month())
		i += 1
	tsmath_SC_WTemp.setUnits("Deg C")
	tsmath_SC_WTemp.setType("PER-AVER")
	tsmath_SC_WTemp.setTimeInterval("1DAY")
	tsmath_SC_WTemp.setLocation("South Canal")
	tsmath_SC_WTemp.setParameterPart("TEMP-WATER")
	tsmath_SC_WTemp.setVersion(BC_F_part)
	tsmath_list.append(tsmath_SC_WTemp)

	if DEBUG:
		temperature_logfile.close()


	########################
	# Municipal withdrawals for Carmichael (Bajamount WTP) and Sacramento (Faibairn)
	########################

	# For each municipal withdrawal location, locate its configured pattern
	# DSS file/path, read the pattern (12 monthly values), and build a daily
	# flow series by repeating each month's pattern value across its days.
	flow_pattern_config_lines = getConfigLines(flow_pattern_config_filename)
	#print "Flow Pattern config file contents:"
	#for line in flow_pattern_config_lines: print "\t%s"%line
	for muni_withdrawal_location in ("CARMICHAEL", "SACRAMENTO"):
		for line in flow_pattern_config_lines:
			token = line.strip().split(',')
			if len(token) != 3:
				print "File %s line \n\t \"%s\"\nis not a valid ID for a flow pattern DSS record."%(flow_pattern_config_filename,line)
				continue
			if line.split(',')[0].strip().upper() == muni_withdrawal_location:
				pattern_DSS_file_name = line.split(',')[1].strip().strip('\\')
				pattern_path = line.split(',')[2].strip()
		if len(pattern_DSS_file_name) == 0 or len(pattern_path) == 0:
			print "Error reading flow pattern configuration file\n\t%s"%(flow_pattern_config_filename)
			print "%s pattern DSS file or path not found."%(muni_withdrawal_location)
			return None
		if not os.path.isabs(pattern_DSS_file_name):
			pattern_DSS_file_name = os.path.join(Project.getCurrentProject().getWorkspacePath(), pattern_DSS_file_name)
			# print "Flow pattern for Folsom in \n\t%s"%(pattern_DSS_file_name)
			# print "\t" + pattern_path

		ts_muni = hec.heclib.dss.HecTimeSeries()
		ts_muni.setDSSFileName(pattern_DSS_file_name)
		print "reading pattern from file: " + pattern_DSS_file_name
		print "\t" + pattern_path
		tsc_muni_pattern = tscont()
		tsc_muni_pattern.fullName = pattern_path
		status = ts_muni.read(tsc_muni_pattern, False)
		ts_muni.done()
		if status < 0:
			print "Failed to read municipal withdrawal time series %s \n\tfrom DSS file %s"%(source_path, source_DSS_file_name)
			continue

		# Build a daily time series and assign each day the pattern value
		# for its calendar month (pattern index = month number - 1).
		tsc_muni = tsmath.generateRegularIntervalTimeSeries(start_time.dateAndTime(4), end_time.dateAndTime(4), "1DAY", "", 1.0).getData()
		in_time = HecTime( HecTime.MINUTE_INCREMENT)
		for i in range(tsc_muni.numberValues):
			in_time.set(tsc_muni.times[i])
			tsc_muni.values[i] = tsc_muni_pattern.values[in_time.month()-1]
			if DEBUG: print "i: %d; patternValue: %f; tsc_value: %f"%(i, tsc_muni_pattern.values[in_time.month()-1],tsc_muni.values[i])
		tsmath_muni = tsmath(tsc_muni)
		tsmath_muni.setWatershed("AMERICAN RIVER")
		tsmath_muni.setLocation(muni_withdrawal_location)
		tsmath_muni.setType("PER-AVER")
		tsmath_muni.setUnits("cfs")
		tsmath_muni.setParameterPart("FLOW-MUNICIPAL")
		tsmath_muni.setVersion(BC_F_part)
		tsmath_list.append(tsmath_muni)

	########################
	# Zero-Flow Time Series
	########################

	# Create daily and hourly zero-flow series for boundary locations that
	# require a valid DSS flow record even when no flow is prescribed.
	tsmath_zero_flow_day = tsmath.generateRegularIntervalTimeSeries(
		"%s 0000"%(start_time.date(4)),
		"%s 2400"%(end_time.date(4)),
		"1DAY", "0M", 0.0)
	tsmath_zero_flow_day.setUnits("CFS")
	tsmath_zero_flow_day.setType("PER-AVER")
	tsmath_zero_flow_day.setTimeInterval("1DAY")
	tsmath_zero_flow_day.setLocation("ZERO-BY-DAY")
	tsmath_zero_flow_day.setParameterPart("FLOW-ZERO")
	tsmath_zero_flow_day.setVersion(BC_F_part)
	tsmath_list.append(tsmath_zero_flow_day)

	tsmath_zero_flow_hour = tsmath.generateRegularIntervalTimeSeries(
		"%s 0000"%(start_time.date(4)),
		"%s 2400"%(end_time.date(4)),
		"1HOUR", "0M", 0.0)
	tsmath_zero_flow_hour.setUnits("CFS")
	tsmath_zero_flow_hour.setType("PER-AVER")
	tsmath_zero_flow_hour.setTimeInterval("1Hour")
	tsmath_zero_flow_hour.setLocation("ZERO-BY-HOUR")
	tsmath_zero_flow_hour.setParameterPart("FLOW-ZERO")
	tsmath_zero_flow_hour.setVersion(BC_F_part)
	tsmath_list.append(tsmath_zero_flow_hour)

	# Write every generated TimeSeriesMath record to the boundary-condition
	# DSS file and construct the corresponding location/path map entry.
	for tsmath_item in tsmath_list:
		ts_write = hec.heclib.dss.HecTimeSeries()
		ts_write.setDSSFileName(BC_output_DSS_filename)
		tsc = tsmath_item.getData()
		rv_lines.append("%s,%s,%s,%s"%(
			tsc.location, tsc.parameter,
			Project.getCurrentProject().getRelativePath(BC_output_DSS_filename),
			tsc.fullName))
		print "\t%s"%rv_lines[-1]
		ts_write.write(tsc)
		ts_write.done()

	return rv_lines

def monthFromDateStr(str):
	"""Extract a three-letter month abbreviation from a date-like string.

	Parameters
	----------
	str : str
		Whitespace-separated string expected to contain a recognizable
		three-letter month abbreviation token.

	Returns
	-------
	str or None
		The matching month abbreviation in upper case, or ``None`` if no
		token in the string matches a recognized abbreviation.
	"""
	month_TLA = ["NM", "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
	for token in str.split():
		if token.strip().upper() in month_TLA:
			return token.strip().upper()
	return None