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

DEBUG = False

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

	print "\nPreparing Meteorological Data..."

	met_lines = create_positional_analysis_met_data(AP_start_time.year(), position_analysis_year, AP_start_time, AP_end_time,
		position_analysis_config_filename, met_output_DSS_filename, met_F_part)
	with open(os.path.join(Project.getCurrentProject().getWorkspacePath(), DSS_map_filename), "w") as mapfile:
		mapfile.write("location,parameter,dss file,dss path\n")
		for line in met_lines:
			mapfile.write(line + '\n')
			if DEBUG: print(line)

	print("Met process complete.\n\nPreparing hydro and WC boundary conditions...")

	ops_lines = create_ops_BC_data(ops_file_name, AP_start_time, AP_end_time,
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
	print "Met output DSS file: %s"%(met_output_DSS_filename)
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
		ts_read = hec.heclib.dss.HecTimeSeries()
		ts_read.setDSSFileName(source_DSS_file_name)
		if DEBUG: print "Reading %s from DSS file %s."%(token[3].strip(), source_DSS_file_name)
		source_path_parts = token[3].strip().strip('/').split('/', 5)
		source_path = '/'
		for index in (0,1,2,4,5):
			source_path += (source_path_parts[index] + '/')
			if index == 2: source_path += '/'
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
		padded_end_time = HecTime()
		padded_end_time.set(end_time.value() + 1440)
		tsmath_shift = tsmath.generateRegularIntervalTimeSeries(
			"%s 0000"%(start_time.date(4)),
			"%s 2400"%(padded_end_time.date(4)),
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
		ts_write = hec.heclib.dss.HecTimeSeries()
		ts_write.setDSSFileName(met_output_DSS_filename)
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

def interpolate_coeffs(year, month, day, coeff_dict):
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
	'''CARDNO/Stantec North Fork American water temperature regression into Folsom
	returns degrees C'''
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

	if rv > 100 or rv < -100:
		return Constants.UNDEFINED
	return rv

def american_SF_temp(year, month, day, SF_cms, T_air):
	'''CARDNO/Stantec South Fork American water temperature regression into Folsom
	returns degrees C'''
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
	if rv > 100 or rv < -100:
		return Constants.UNDEFINED
	return rv

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
def create_ops_BC_data(ops_file_name, start_time, end_time, BC_output_DSS_filename,
	BC_F_part, ops_import_F_part, flow_pattern_config_filename, DSS_map_filename):
	print "Processing boundary conditions for American River from ops file:\n\t%s"%(ops_file_name)
	print "  Forecast time window start: %s"%(start_time.dateAndTime(4))
	print "  Forecast time window end: %s"%(end_time.dateAndTime(4))


	forecast_locations = ["Trinity/Clair Engle", "Whiskeytown", "Shasta", "Oroville", "Folsom", "New Melones", " SAN LUIS/O'NEILL", "DELTA"]
	active_locations = ["Folsom"]

	rv_lines = []

	if ops_file_name.endswith(".xls") or ops_file_name.endswith(".xlsx"):
		try:
			ops_data = CVP.import_CVP_Ops_xls(ops_file_name, forecast_locations, active_locations)
		except Exception as e:
			print "Failed to read operations file:%s"%ops_file_name
			print "\t%s"%str(e)
			return None
	else:
		ops_data = CVP.import_CVP_Ops_csv(ops_file_name, forecast_locations, active_locations)

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
			if len(date_parts[2]) < 4: date_parts[2] = "20" + date_parts[2]
			profile_date = "%s%s%s"%(date_parts[0],date_parts[1],date_parts[2])
		except Exception as e:
			print "Failed to read profile date from string:%s"%profile_date
			print "\t%s"%str(e)
			return None
		print "Profile date: %s"%profile_date

	folsom_tsc_list = []
	folsom_calendar = ops_data["Folsom"][0].split(',')
	start_index = int(folsom_calendar[0])
	start_month = folsom_calendar[start_index + 1].strip().upper()
	if DEBUG: print "\n Folsom start month: %s; Start index: %d"%(start_month, start_index)

	ops_start_date = HecTime()
	days_in_first_month = None
	if profile_date:
		ops_start_date.set(profile_date, "2400")
		days_in_first_month = 1 + CVP.get_days_in_month(CVP.month_index(start_month), ops_start_date.year()) - ops_start_date.day()
	else:
		ops_start_date.set("01%s%d"%(start_month, start_time.year()), "0000")
		if ops_start_date > start_time:
			ops_start_date.set("01%s%d"%(start_month, start_time.year()-1), "0000")

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
			tsmath_folsom_evap_monthly = tsmath(ts)
			tsmath_list.append(tsmath_folsom_evap_monthly)
			tsmath_folsom_acc_dep = tsmath_folsom_acc_dep.subtract(
				CVP.uniform_transform_monthly_to_daily(tsmath(ts), start_day_count=days_in_first_month))
		elif "STORAGE" in ts.parameter.upper():
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
			tsmath_release_monthly = tsmath(ts)
			tsmath_list.append(tsmath_release_monthly)
			tsmath_release = CVP.uniform_transform_monthly_to_hourly(tsmath(ts), start_day_count=days_in_first_month)
			tsmath_release.setPathname(ts.fullName)
			tsmath_release.setTimeInterval("1HOUR")
			tsmath_release.setParameterPart("FLOW-RELEASE")
			tsmath_release.setVersion(BC_F_part)
			tsmath_list.append(tsmath_release)
		elif ts.parameter.upper() == "ACTUAL NIMBUS RELEASE (TAF)":
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
	tsmath_list.append(tsmath_storage_daily)
	tsmath_list.append(tsmath_folsom_acc_dep)

	########################
	# Disaggregate Folsom Tributary In Flows
	########################

	# North Fork and South Fork coefficients
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

	# North Fork and Middle Fork coefficients as fraction of total NF flow to Folsom
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
		tsmath_shift = shift_monthly_averages(tsmath_avg, start_time, end_time)
		shift_path = token[-1].strip().split('/')
		shift_path[6] = BC_F_part
		tsmath_shift.getContainer().fullName = '/'.join(shift_path)
		tsmath_list.append(CVP.uniform_transform_monthly_to_daily(tsmath_shift, start_day_count=days_in_first_month))
		ts_read.done()


	########################
	# Estimate Folsom Tributary Temperatures
	########################

	std_out_restore = sys.stdout
	if DEBUG:
		temperature_logfile = open(os.path.join(Project.getCurrentProject().getWorkspacePath(), "AMR_temp_calc.log"), 'w')
		sys.stdout = temperature_logfile

	# South Fork water temperature from regression formula
	if names_flows["Folsom-SF-in"].isMetric():
		tsmath_SF_cms = names_flows["Folsom-SF-in"]
	else:
		tsmath_SF_cms = names_flows["Folsom-SF-in"].convertToMetricUnits()

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
	tsmath_SF_WTemp = tsmath.generateRegularIntervalTimeSeries(start_time.dateAndTime(4), end_time.dateAndTime(4), "1DAY", "", 0.0)
	time_post = HecTime(HecTime.MINUTE_INCREMENT)
	i = 0
	SF = tsmath_SF_cms.getContainer()
	T = tsmath_T_air_daily.getContainer()
	for time_step in tsmath_SF_WTemp.getContainer().times:
		time_post.set(time_step)
		#print(time_step,SF.times[0],SF.times[-1],T.times[0],T.times[-1])
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
		sys.stdout = std_out_restore
		temperature_logfile.close()


	########################
	# Municipal withdrawals for Carmichael (Bajamount WTP) and Sacramento (Faibairn)
	########################

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
	month_TLA = ["NM", "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
	for token in str.split():
		if token.strip().upper() in month_TLA:
			return token.strip().upper()
	return None

