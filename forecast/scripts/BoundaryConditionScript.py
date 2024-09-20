import os, sys
import math
import re
from com.rma.io import DssFileManagerImpl
from com.rma.model import Project

import hec.heclib.dss
import hec.heclib.util.HecTime as HecTime
import hec.io.TimeSeriesContainer as tscont
import hec.hecmath.TimeSeriesMath as tsmath
from hec.script import MessageBox

import usbr.wat.plugins.actionpanel.model.forecast as fc
sys.path.append(os.path.join(Project.getCurrentProject().getWorkspacePath(), "forecast", "scripts"))

import CVP_ops_tools as CVP
reload(CVP)

DEBUG = True

'''Accepts parameters for WTMP forecast runs to form boundary condition data sets.'''
def build_BC_data_sets(AP_start_time, AP_end_time, BC_F_part, BC_output_DSS_filename, ops_file_name, DSS_map_filename,
		position_analysis_year=None,
		position_analysis_config_filename=None,
		met_F_part=None,
		met_output_DSS_filename=None,
		flow_pattern_config_filename=None,
		ops_import_F_part=None):

	# Postitional (required) args:
	# AP_start_time (HecTime) start of the simulation group run time
	# AP_end_time (HecTime) end of the simulation group run time
	# BC_F_part (str) DSS F part for output time series records
	# BC_output_DSS_filename (str) Name of DSS file for output time series records. Assumed relative to study directory
	# ops_file_name (str) Name of CVP ops data spreadsheet file
	# DSS_map_filename (str) Name of file where list of output locactions and DSS records will be written.  Assumed relative to study directory

	# Key-word (optional) args (kwargs):
	# position_analysis_year (int) Source year for met data position analysis (positional analysis args are needed until there are other methods for making met data)
	# position_analysis_config_filename (str) Name of file holding list of source time series for position analysis. Assumed relative to study directory. Defaults to forecast/config/historical_met.config
	# met_F_part (str) DSS F part for met data specifically. Defaults to BC_F_part
	# met_output_DSS_filename (str) Name of separate DSS file for met time series records. Assumed relative to study directory. Defaults to BC_output_DSS_filename
	# flow_pattern_config_filename (str) Name of file holding list of pattern time series for flow disaggreagtion. Assumed relative to study directory. Defaults to forecast/config/flow_pattern.config

	position_analysis_config_filename = r"forecast\config\met_editor.config"

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

	print "\n########"
	print "\tGenerating Boundary Conditions for American River models"
	print "########\n"

	print "CVP Ops Data file: %s"%ops_file_name
	print "Met data config file: %s"%position_analysis_config_filename
	print "Flow pattern config file: %s"%flow_pattern_config_filename
	print "Boundary Condition output DSS file: %s"%BC_output_DSS_filename
	print "Met data output DSS file: %s"%met_output_DSS_filename
	print "Location/Path map file: %s"%DSS_map_filename

	if AP_start_time.month() < 10:
		target_year = AP_start_time.year()
	else:
		target_year = AP_end_time.year()

	print "\nPreparing Meteorological Data..."

	met_lines = create_positional_analysis_met_data(target_year, position_analysis_year, AP_start_time, AP_end_time,
		position_analysis_config_filename, met_output_DSS_filename, met_F_part)
	with open(os.path.join(Project.getCurrentProject().getWorkspacePath(), DSS_map_filename), "w") as mapfile:
		mapfile.write("location,parameter,dss file,dss path\n")
		for line in met_lines:
			mapfile.write(line + '\n')
			if DEBUG: print(line)

	print("Met process complete.\n\nPreparing hydro and WC boundary conditions...")

	ops_lines = create_ops_BC_data(target_year, ops_file_name, AP_start_time, AP_end_time,
		BC_output_DSS_filename, BC_F_part, ops_import_F_part, flow_pattern_config_filename, DSS_map_filename)
	if not ops_lines:
		return 0

	with open(os.path.join(Project.getCurrentProject().getWorkspacePath(), DSS_map_filename), "a") as mapfile:
		for line in ops_lines:
			mapfile.write(line)
			mapfile.write('\n')
	print "\nBoundary condition report written to: %s\n"%(DSS_map_filename)

	return len(met_lines) + len(ops_lines)


'''
Simple time-shifter for met positional ananlysis data

This function doesn't contain any location-specific data or configuration. All necessary
location and DSS file/path combinations are provided in a position analysis configuration file.
'''
def create_positional_analysis_met_data(target_year, source_year, start_time, end_time,
position_analysis_config_filename, met_output_DSS_filename, met_F_part):
	print "Calculating positional met data..."
	print "Historical Met File: %s"%(fc.ForecastConfigFiles.getHistoricalMetFile())
	print "Position Analysis Met File: %s"%position_analysis_config_filename
	diff_years = target_year - source_year
	print "Shifting met data from %d to %d (%d years)."%(source_year, target_year, diff_years)

	rv_lines = []
	met_config_str = ""
	DSSout = hec.heclib.dss.HecDss.open(met_output_DSS_filename)
	met_config_lines = getConfigLines(position_analysis_config_filename)
	for line in met_config_lines[1:]:
		token = line.strip().split(',')
		dest_count = 0
		try:
			dest_count = int(token[4])
		except:
			print "File %s line \n\t \"%s\"\nis not a valid ID for a position analysis DSS record."%(position_analysis_config_filename,line)
			print "Can't read an integer value from \"%s\"."%(token[4])
			continue
		target_line_length = 5 + 2*dest_count
		if len(token) != target_line_length:
			print "File %s line \n\t \"%s\"\nis not a valid ID for a position analysis DSS record."%(position_analysis_config_filename,line)
			continue
		#source_DSS_file_name = os.path.join(Project.getCurrentProject().getWorkspacePath(), token[0].strip('\\'))
		source_DSS_file_name = os.path.join(Project.getCurrentProject().getWorkspacePath(), token[2].strip().strip('\\'))
		DSSsource = hec.heclib.dss.HecDss.open(source_DSS_file_name)
		if DEBUG: print "Reading %s from DSS file %s."%(token[3].strip(), source_DSS_file_name)
		source_path_parts = token[3].strip().strip('/').split('/', 5)
		source_path = '/'
		for index in (0,1,2,4,5):
			source_path += (source_path_parts[index] + '/')
			if index == 2: source_path += '/'
		tsmath_source = DSSsource.read(source_path)
		time_step_label = token[3].strip().split('/')[5]
		if DEBUG:  print "\tTime series contains %d values."%(tsmath_source.getContainer().numberValues)
		if DEBUG:  print "\tShifting time series with shiftInTime(%s)."%("%dMo"%(diff_years*12))
		# tsmath_shift = tsmath_source.shiftInTime("%dYrar"%(diff_years))
		tsmath_shift = tsmath.generateRegularIntervalTimeSeries(
			"%s 0000"%(start_time.date(4)),
			"%s 2400"%(end_time.date(4)),
			time_step_label, "0M", 1.0)
		time_seek = HecTime(tsmath_shift.firstValidDate(), HecTime.MINUTE_INCREMENT)
		time_seek.setYearMonthDay(time_seek.year() - diff_years, time_seek.month(), time_seek.day(), time_seek.minutesSinceMidnight())
		if time_seek.getMinutes() < tsmath_source.firstValidDate():
			print "Met position time shift out of range at source start..."
			return ['']
		source_container = tsmath_source.getContainer()
		shift_container = tsmath_shift.getContainer()
		start_index = 0
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
		if len(shift_container.values) != shift_container.numberValues:
			print "You doofus!\nlen(values)=%d\nnumberValues=%d\n"%(len(shift_container.values), shift_container.numberValues)
			return ['']
		tsmath_shift.setType(tsmath_source.getType())
		tsmath_shift.setUnits(tsmath_source.getUnits())
		tsmath_shift.setPathname(tsmath_source.getContainer().fullName)
		tsmath_shift.setVersion(met_F_part)
		DSSout.write(tsmath_shift)
		DSSsource.done()

		#met_loc, met_param = token[1].strip().split('<', 1)
		met_loc = token[0]
		met_param = token[1]
		rv_lines.append("%s,%s,%s,%s"%(met_loc.strip(), met_param.strip().strip('>'),
		Project.getCurrentProject().getRelativePath(met_output_DSS_filename),
		tsmath_shift.getContainer().fullName))

	return rv_lines

def shift_monthly_averages(source_tsm, AP_start_time, AP_end_time):
	# source_tsm -- time series math of monthly average values
	# AP_start_time, AP_end_time -- HecTime objects

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
	commentRE = re.compile(r"<!--.*?-->", re.S)
	hashCommentRE = re.compile(r"#.*")
	with open(fileName) as infile:
		config_str = infile.read()
	config_str = commentRE.sub("", config_str)
	config_str = hashCommentRE.sub("", config_str).strip()
	config_str = re.sub(r"\n+", "\n", config_str)
	return  config_str.split('\n')

def american_NF_temp(month, NF_cms, MF_cms, T_air):
	'''CARDNO/Stantec North Fork American water temperature regression into Folsom
	returns degrees C'''
	NF_coeff = {
		1: [3.774, 1.266, -0.123, 0.209],
		2: [5.013, 2.088, -2.308, 0.289],
		3: [7.568, 3.042, -4.644, 0.336],
		4: [13.929, 1.493, -5.956, 0.278],
		5: [19.23, -4.149, -2.651, 0.279],
		6: [22.008, -2.190, -4.320, 0.182],
		7: [27.481, 0.461, -8.106, 0.071],
		8: [26.076, -0.056, -7.756, 0.064],
		9: [19.876, -2.334, -4.285, 0.107],
		10: [11.463, 0.665, -2.909, 0.355],
		11: [7.827, 0.685, -1.342, 0.367],
		12: [3.52, -0.27, 1.59, 0.30]
	}
	coeff = NF_coeff[month]
	return coeff[0] + coeff[1] * math.log10(NF_cms) + coeff[2] * math.log10(MF_cms) + coeff[3] * T_air

def american_SF_temp(month, SF_cms, T_air):
	'''CARDNO/Stantec South Fork American water temperature regression into Folsom
	returns degrees C'''
	SF_coeff = {
		1: [1.956, 1.374, 0.290],
		2: [3.894, 0.221, 0.282],
		3: [8.456, -1.422, 0.224],
		4: [12.605, -3.050, 0.223],
		5: [19.374, -5.815, 0.204],
		6: [22.03, -6.605, 0.216],
		7: [23.604, -5.623, 0.114],
		8: [21.761, -5.196, 0.105],
		9: [17.663, -4.067, 0.155],
		10: [11.832, -2.665, 0.299],
		11: [6.521, -0.366, 0.374],
		12: [3.430, 0.755, 0.358]
	}
	coeff = SF_coeff[month]
	return coeff[0] + coeff[1] * math.log10(SF_cms) + coeff[2] * T_air

def american_SC_temp(month):
	'''CARDNO/Stantec South Canal monthly average inflow temperature into Folsom
	returns degrees C
	'''
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


'''Processes the contents of the CVP ops spreadsheet in to flow and water temperature BCs'''
def create_ops_BC_data(target_year, ops_file_name, start_time, end_time, BC_output_DSS_filename,
	BC_F_part, ops_import_F_part, flow_pattern_config_filename, DSS_map_filename):
	print "Processing boundary conditions for American River from ops file:\n\t%s"%(ops_file_name)
	print "  Forecast time window start: %s"%(start_time.dateAndTime(4))
	print "  Forecast time window end: %s"%(end_time.dateAndTime(4))


	forecast_locations = ["Trinity/Clair Engle", "Whiskeytown", "Shasta", "Oroville", "Folsom", "New Melones", " SAN LUIS/O'NEILL", "DELTA"]
	active_locations = ["Folsom"]

	rv_lines = []
	open_DSS_files = []

	if ops_file_name.endswith(".xls") or ops_file_name.endswith(".xlsx"):
		try:
			ops_data = CVP.import_CVP_Ops_xls(ops_file_name, forecast_locations)
		except Exception as e:
			print "Failed to read operations file:%s"%ops_file_name
			print "\t%s"%str(e)
			return None
	else:
		ops_data = CVP.import_CVP_Ops_csv(ops_file_name, forecast_locations)

	profile_date = None

	for key in ops_data.keys():
		if DEBUG:
			print "ops_data key: %s"%(key)
		if ops_data[key][1].strip().upper().startswith("PROFILEDATE"):
			profile_date = ops_data[key][1].split(':')[1].strip()
			del ops_data[key][1]

	if profile_date:
		try:
			date_parts = profile_date.split('-', 2)
			profile_date = "%s%s20%s"%(date_parts[0],date_parts[1],date_parts[2])
		except Exception as e:
			print "Failed to read profile date from string:%s"%profile_date
			print "\t%s"%str(e)
			return None
		print "Profile date: %s"%profile_date

	folsom_ts_list = []
	folsom_calendar = ops_data["Folsom"][0].split(',')
	start_index = int(folsom_calendar[0])
	start_month = folsom_calendar[start_index + 1].strip().upper()
	if DEBUG: print "\n Folsom start month: %s; Start index: %d"%(start_month, start_index)
	for line in ops_data["Folsom"][1:]:
		data_month = start_month
		data_year = target_year
		try:
			early_val = float(line.split(',')[start_index - 1].strip())
			data_month = CVP.month_TLA[CVP.previous_month(CVP.month_index(start_month))]
			if data_month == "DEC":
				data_year -= 1
		except:
			pass
		if DEBUG: print "Start_index = %d\nData_Month = %s"%(start_index, data_month)
		if DEBUG: print "Passing line to CVP.make_ops_tsc: %s"%(line)
		folsom_ts_list.append(CVP.make_ops_tsc("FOLSOM", data_year, data_month, line, ops_label=ops_import_F_part))

	'''
	Disabled code for temporal pattern
	To restore:
		1. Remove block comment here
		2. Find computation that creates tsmath_daily_flow and switch from uniform
			to weighted disaggregation of inflow volume
		3. Just above return statement for this function, restore patternDSS.done()
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

	patternDSS = hec.heclib.dss.HecDss.open(pattern_DSS_file_name)
	open_DSS_files.append(patternDSS)
	'''

	DSS_map_lines = getConfigLines(DSS_map_filename)
	#print "DSS map config file contents:"
	#for line in DSS_map_lines: print "\t%s"%line

	met_DSS_file_name = ""
	airtemp_path = ""
	for line in DSS_map_lines:
		if (line.split(',')[0].strip().upper() == "FAIR OAKS" and
			line.split(',')[1].strip().upper() == "AIR TEMPERATURE"):
			met_DSS_file_name = line.split(',')[2].strip().strip('\\')
			airtemp_path = line.split(',')[3].strip()
	if len(met_DSS_file_name) == 0 or len(airtemp_path) == 0:
		print "Error reading Fair Oaks air temperature data configuration from file\n\t%s"%(DSS_map_filename)
		print "Air temperature DSS file or path not found."
		return None
	if not os.path.isabs(met_DSS_file_name):
		met_DSS_file_name = os.path.join(Project.getCurrentProject().getWorkspacePath(), met_DSS_file_name)


	outDSS = hec.heclib.dss.HecDss.open(BC_output_DSS_filename)
	open_DSS_files.append(outDSS)
	temperatureDSS = hec.heclib.dss.HecDss.open(met_DSS_file_name)
	open_DSS_files.append(temperatureDSS)

	ops_start_date = HecTime()
	ops_end_date = HecTime()
	days_in_first_month = None
	if profile_date:
		ops_start_date.set(profile_date, "2400")
		days_in_first_month = 1 + CVP.get_days_in_month(CVP.month_index(start_month), ops_start_date.year()) - ops_start_date.day()
	else:
		ops_start_date.set("01%s%d"%(start_month, target_year), "2400")
	ops_end_date.set(folsom_ts_list[0].getHecTime(folsom_ts_list[0].numberValues - 1))

	########################
	# Folsom data from CVP spreadsheet
	########################

	tsm_list = []
	print "TS Location = %s"%(folsom_ts_list[0].location.upper())
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
	for ts in folsom_ts_list:
		print "\tTS Parameter = %s"%(ts.parameter.upper())
		if ts.parameter.upper() == "INFLOW":
			tsmath_flow_monthly = tsmath(ts)
			tsm_list.append(tsmath_flow_monthly)
			# print "reading pattern from file: " + pattern_DSS_file_name
			# print "\t" + pattern_path
			# tsmath_pattern = patternDSS.read(pattern_path)
			# tsmath_daily_flow = CVP.weight_transform_monthly_to_daily(tsmath(ts), tsmath_pattern, start_day_count=days_in_first_month)
			tsmath_daily_flow = CVP.uniform_transform_monthly_to_daily(tsmath(ts), start_day_count=days_in_first_month)
			tsmath_daily_flow.setPathname(ts.fullName)
			tsmath_daily_flow.setTimeInterval("1DAY")
			tsmath_daily_flow.setParameterPart("FLOW-IN")
			tsmath_daily_flow.setVersion(BC_F_part)
			tsm_list.append(tsmath_daily_flow)
		elif ts.parameter.upper() == "EST. EVAP.":
			tsmath_folsom_evap_monthly = tsmath(ts)
			tsm_list.append(tsmath_folsom_evap_monthly)
			tsmath_folsom_acc_dep = tsmath_folsom_acc_dep.subtract(
				CVP.uniform_transform_monthly_to_daily(tsmath(ts), start_day_count=days_in_first_month))
		elif "STORAGE" in ts.parameter.upper():
			tsmath_storage_monthly =  tsmath(ts)
			tsmath_storage_monthly.setParameterPart("STORAGE")
			tsmath_storage_monthly.setType("INST-CUM")
			tsm_storage_change = tsmath_storage_monthly.successiveDifferences()
			tsmath_storage_monthly.setType("INST-VAL")
			tsm_list.append(tsmath_storage_monthly)
			tsm_storage_change.setWatershed("")
			tsm_storage_change.setLocation("FOLSOM LAKE")
			tsm_storage_change.setParameterPart("STORAGE-CHANGE")
			tsm_list.append(tsm_storage_change)
		elif ts.parameter.upper() == "TOTAL RELEASE":
			tsmath_release_monthly = tsmath(ts)
			tsm_list.append(tsmath_release_monthly)
			tsmath_release = CVP.uniform_transform_monthly_to_hourly(tsmath(ts), start_day_count=days_in_first_month)
			tsmath_release.setPathname(ts.fullName)
			tsmath_release.setTimeInterval("1HOUR")
			tsmath_release.setParameterPart("FLOW-RELEASE")
			tsmath_release.setVersion(BC_F_part)
			tsm_list.append(tsmath_release)
		elif ts.parameter.upper() == "ACTUAL NIMBUS RELEASE (TAF)":
			tsmath_nimbus_monthly = tsmath(ts)
			tsmath_nimbus_monthly.setWatershed("AMERICAN RIVER")
			tsmath_nimbus_monthly.setLocation("LAKE NATOMA")
			tsm_list.append(tsmath_nimbus_monthly)
			tsmath_nimbus = CVP.uniform_transform_monthly_to_daily(tsmath_nimbus_monthly, start_day_count=days_in_first_month)
			tsmath_nimbus.setPathname(ts.fullName)
			tsmath_nimbus.setWatershed("AMERICAN RIVER")
			tsmath_nimbus.setLocation("LAKE NATOMA")
			tsmath_nimbus.setParameterPart("FLOW-NIMBUS ACTUAL")
			tsmath_nimbus.setTimeInterval("1DAY")
			tsmath_nimbus.setVersion(BC_F_part)
			tsm_list.append(tsmath_nimbus)
		elif ts.parameter.upper() == "FLOW-AMER AFRP":
			ts.units = "CFS"
			ts.type = "PER-AVER"
			tsmath_afrp_monthly = tsmath(ts)
			tsm_list.append(tsmath_afrp_monthly)
			tsmath_afrp = CVP.uniform_transform_monthly_to_daily(tsmath(ts), start_day_count=days_in_first_month)
			tsmath_afrp.setPathname(ts.fullName)
			tsmath_afrp.getContainer().parameter = "FLOW-AFRP"
			tsmath_afrp.setTimeInterval("1DAY")
			tsmath_afrp.setVersion(BC_F_part)
			tsm_list.append(tsmath_afrp)
		elif ts.parameter.upper() == "PUMPING (FP)":
			tsmath_fp_monthly = tsmath(ts)
			tsm_list.append(tsmath_fp_monthly)
			tsmath_fp = CVP.uniform_transform_monthly_to_daily(tsmath(ts), start_day_count=days_in_first_month)
			tsmath_fp.setPathname(ts.fullName)
			tsmath_fp.getContainer().parameter = "FLOW-PUMPING"
			tsmath_fp.setTimeInterval("1DAY")
			tsmath_fp.setVersion(BC_F_part)
			tsm_list.append(tsmath_fp)
		elif ts.parameter.upper() == "FS CANAL (FSC)":
			tsmath_fsc_monthly = tsmath(ts)
			tsm_list.append(tsmath_fsc_monthly)
			tsmath_fsc = CVP.uniform_transform_monthly_to_daily(tsmath(ts), start_day_count=days_in_first_month)
			tsmath_fsc.setPathname(ts.fullName)
			tsmath_fsc.getContainer().parameter = "FLOW-FSC"
			tsmath_fsc.setTimeInterval("1DAY")
			tsmath_fsc.setVersion(BC_F_part)
			tsm_list.append(tsmath_fsc)
		else:
			tsm_list.append(tsmath(ts))

	# Folsom storage changes due to:
	#	In:
	#		Folsom inflow : tsmath_daily_flow
	#	Out:
	#		Folsom dam releases: tsmath_release_daily
	#		Net evaporation, leakage, other: tsmath_acc_dep

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
	tsm_list.append(tsmath_storage_daily)
	tsm_list.append(tsmath_folsom_acc_dep)

	########################
	# Disaggregate Folsom Tributary In Flows
	########################

	# North Fork and South Fork coefficients
	tributary_weights = {
		"Folsom-NF-in":(0.62, 0.63, 0.66, 0.61, 0.53, 0.49, 0.49, 0.47, 0.50, 0.39, 0.54, 0.61),
		"Folsom-SF-in":(0.38, 0.37, 0.34, 0.39, 0.47, 0.57, 0.57, 0.53, 0.50, 0.61, 0.46, 0.39)}
	names_flows = {}
	for tsm in CVP.split_time_series_monthly(tsmath_daily_flow, tributary_weights, "FLOW-IN"):
		tsm.setVersion(BC_F_part)
		tsm_list.append(tsm)
		names_flows[tsm.getContainer().location] = tsm

	# North Fork and Middle Fork coefficients as fraction of total NF flow to Folsom
	NF_tributary_weights ={
		"North Fork abv MF":(0.40, 0.45, 0.49, 0.52, 0.51, 0.33, 0.15, 0.08, 0.09, 0.22, 0.24, 0.33),
		"Middle Fork abv NF":(0.60, 0.55, 0.51, 0.48, 0.49, 0.67, 0.85, 0.92, 0.91, 0.78, 0.76, 0.67)}
	for tsm in CVP.split_time_series_monthly(names_flows["Folsom-NF-in"], NF_tributary_weights, "FLOW-IN"):
		tsm.setVersion(BC_F_part)
		tsm_list.append(tsm)
		names_flows[tsm.getContainer().location] = tsm

	########################
	# Get flows and temperatures for downstream tributaries, and other seasonal stuff
	# from monthly average data sets
	########################

	tributary_config_filename = os.path.join(Project.getCurrentProject().getWorkspacePath(), r"forecast\config\tributary_averages.config")
	trib_DSS_files = {}
	for line in getConfigLines(tributary_config_filename):
		token = line.split(',')
		dss_file_name = token[-2].strip()
		if not os.path.isabs(dss_file_name):
			dss_file_name = os.path.join(Project.getCurrentProject().getWorkspacePath(), dss_file_name)
		if not trib_DSS_files.get(dss_file_name):
			trib_DSS_files[dss_file_name] = hec.heclib.dss.HecDss.open(dss_file_name)
		tsmath_avg = tsmath(trib_DSS_files[dss_file_name].get(token[-1].strip()))
		tsmath_shift = shift_monthly_averages(tsmath_avg, start_time, end_time)
		shift_path = token[-1].strip().split('/')
		shift_path[6] = BC_F_part
		tsmath_shift.getContainer().fullName = '/'.join(shift_path)
		tsm_list.append(CVP.uniform_transform_monthly_to_daily(tsmath_shift, start_day_count=days_in_first_month))
	for fname in trib_DSS_files:
		trib_DSS_files[fname].done()


	########################
	# Estimate Folsom Tributary Temperatures
	########################

	# South Fork water temperature from regression formula
	if names_flows["Folsom-SF-in"].isMetric():
		tsmath_SF_cms = names_flows["Folsom-SF-in"]
	else:
		tsmath_SF_cms = names_flows["Folsom-SF-in"].convertToMetricUnits()
	tsmath_airtemp = temperatureDSS.read(airtemp_path)
	if tsmath_airtemp.isMetric():
		tsmath_T_air = tsmath_airtemp
	else:
		tsmath_T_air = tsmath_airtemp.convertToMetricUnits()

	print "South Fork Temp start time = " + start_time.date(4) + ' ' + str(start_time.minutesSinceMidnight())
	print "South Fork Temp end time = " + end_time.date(4) + ' ' + str(end_time.minutesSinceMidnight())
	tsmath_SF_WTemp = tsmath.generateRegularIntervalTimeSeries(start_time.dateAndTime(4), end_time.dateAndTime(4), "1DAY", "", 0.0)
	time_post = HecTime(HecTime.MINUTE_INCREMENT)
	i = 0
	SF = tsmath_SF_cms.getContainer()
	T = tsmath_T_air.getContainer()
	for time_step in tsmath_SF_WTemp.getContainer().times:
		time_post.set(time_step)
		#print(time_step,SF.times[0],SF.times[-1],T.times[0],T.times[-1])
		tsmath_SF_WTemp.getContainer().values[i] = american_SF_temp(time_post.month(),
					tsmath_SF_cms.getContainer().getValue(time_post),
					tsmath_T_air.getContainer().getValue(time_post))
		if DEBUG and time_post.day() % 5 == 0:
			print "DT: %s (%d); SF flow: %.2f; Air Temp: %.2f; SF Water Temp: %.2f"%(
				time_post.dateAndTime(4), time_post.month(),
				tsmath_SF_cms.getContainer().getValue(time_post),
				tsmath_T_air.getContainer().getValue(time_post),
				tsmath_SF_WTemp.getContainer().values[i])
		i += 1
	tsmath_SF_WTemp.setUnits("Deg C")
	tsmath_SF_WTemp.setType("PER-AVER")
	tsmath_SF_WTemp.setTimeInterval("1DAY")
	tsmath_SF_WTemp.setLocation("Folsom-SF-in")
	tsmath_SF_WTemp.setParameterPart("TEMP-WATER")
	tsmath_SF_WTemp.setVersion(BC_F_part)
	tsm_list.append(tsmath_SF_WTemp)

	# North Fork water temperature from regression formula
	if names_flows["North Fork abv MF"].isMetric():
		tsmath_NF_cms = names_flows["North Fork abv MF"]
	else:
		tsmath_NF_cms = names_flows["North Fork abv MF"].convertToMetricUnits()
	if names_flows["Middle Fork abv NF"].isMetric():
		tsmath_MF_cms = names_flows["Middle Fork abv NF"]
	else:
		tsmath_MF_cms = names_flows["Middle Fork abv NF"].convertToMetricUnits()

	tsmath_NF_WTemp = tsmath.generateRegularIntervalTimeSeries(start_time.dateAndTime(4), end_time.dateAndTime(4), "1DAY", "", 0.0)
	i = 0
	for time_step in tsmath_NF_WTemp.getContainer().times:
		time_post.set(time_step)
		tsmath_NF_WTemp.getContainer().values[i] = american_NF_temp(time_post.month(),
					tsmath_NF_cms.getContainer().getValue(time_post),
					tsmath_MF_cms.getContainer().getValue(time_post),
					tsmath_T_air.getContainer().getValue(time_post))
		if DEBUG and time_post.day() % 5 == 0:
			print "DT: %s (%d); NF flow: %.2f; MF flow: %.2f; Air Temp: %.2f; NF Water Temp: %.2f"%(
				time_post.dateAndTime(4), time_post.month(),
				tsmath_NF_cms.getContainer().getValue(time_post),
				tsmath_MF_cms.getContainer().getValue(time_post),
				tsmath_T_air.getContainer().getValue(time_post),
				tsmath_SF_WTemp.getContainer().values[i])
		i += 1
	tsmath_NF_WTemp.setUnits("Deg C")
	tsmath_NF_WTemp.setType("PER-AVER")
	tsmath_NF_WTemp.setTimeInterval("1DAY")
	tsmath_NF_WTemp.setLocation("Folsom-NF-in")
	tsmath_NF_WTemp.setParameterPart("TEMP-WATER")
	tsmath_NF_WTemp.setVersion(BC_F_part)
	tsm_list.append(tsmath_NF_WTemp)

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
	tsm_list.append(tsmath_SC_WTemp)

	########################
	# Zero-Flow Time Series
	########################

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
	tsm_list.append(tsmath_zero_flow_day)

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
	tsm_list.append(tsmath_zero_flow_hour)

	for tsmath_item in tsm_list:
		rv_lines.append("%s,%s,%s,%s"%(
			tsmath_item.getContainer().location, tsmath_item.getContainer().parameter,
			Project.getCurrentProject().getRelativePath(BC_output_DSS_filename),
			tsmath_item.getContainer().fullName))
		print "\t%s"%rv_lines[-1]
		outDSS.write(tsmath_item)

	for fp in open_DSS_files:
		fp.done()

	return rv_lines


'''
Imports a CVP ops spreadsheet saved as comma-separated values
Returns a dictionary with keys that match the list of forecast locations in the second argrument
Dictionary values are lists of CSV lines that "belong" to the location named in the key
'''
def import_CVP_Ops_csv(ops_fname, forecast_locations):
	current_location = None
	start_month = None
	first_date_index = -1
	location_count = 0
	ts_count = 0
	data_lines = []
	rv_dictionary = {}
	calendar = ""

	with open(ops_fname) as infile:
		num_lines = 0; num_data_lines = 0
		for line in infile:
			num_lines += 1
			line_contains_months = False
			token = line.strip().split(',')
			# figure out what columns our data start in, what month we're looking at, and ignore blank lines
			# the sample spreadsheet had an unused summary block starting in column AA, which I'm ignoring
			num_t = 0; num_val = 0
			for t in token[:26]:
				if len(t.strip()) > 0:
					num_val += 1
					if not line_contains_months and t.strip().upper() in CVP.month_TLA:
						line_contains_months = True
						first_date_index = num_t
						start_month = t.strip().upper()
						if DEBUG: print "Calendar line %s: "%(line)
						if DEBUG: print "Found \"%s\" in column %d"%(t.strip(), num_t + 1)
						calendar = line
				num_t += 1
			if num_val == 0:
				continue # don't include this line in the result

			if token[0].strip() in forecast_locations and len(calendar) > 0:
				if location_count > 0:
					rv_dictionary[current_location] = data_lines
				data_lines = []
				current_location = token[0].strip()
				print "setting current location to %s"%(current_location)
				data_lines.append("%d,%s"%(first_date_index, calendar.strip()))
				if len(token[1].strip()) > 1:
					print("PROFILEDATE: %s"%(token[1]))
					data_lines.append("PROFILEDATE: %s"%(token[1]))
				location_count += 1
				calendar = ""
				continue

			if not line_contains_months:
				data_lines.append(line.strip())
				ts_count += 1

	rv_dictionary[current_location] = data_lines #
	print "Found %d forecast locations and %d time series in ops file \n\t%s."%(
		location_count, ts_count, ops_fname)
	return rv_dictionary


def monthFromDateStr(str):
	month_TLA = ["NM", "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
	for token in str.split():
		if token.strip().upper() in month_TLA:
			return token.strip().upper()
	return None

