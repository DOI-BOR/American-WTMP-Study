'''
CVP_ops_tools

stuff to process time series data out of Central Valley Progect operations spreadsheets
'''

import hec.heclib.util.HecTime as HecTime
import hec.io.TimeSeriesContainer as tscont
import hec.hecmath.TimeSeriesMath as tsmath
import hec.lang.Const

import java.lang
import java.io.File
import java.io.FileInputStream

from org.apache.poi.xssf.usermodel import XSSFWorkbook
from org.apache.poi.hssf.usermodel import HSSFWorkbook
from org.apache.poi.ss import usermodel as SSUsermodel

DEBUG = True

month_TLA = ["NM", "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
days_in_month = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

def get_days_in_month(month_int, year_int):
	if month_int > 12 or month_int < 1:
		raise ValueError("Month (%d) is not an int between 1 and 12."%(month_int))
	if month_int == 2 and HecTime.isLeap(year_int):
		return 29
	return days_in_month[month_int]

def month_index(s_month):
	if not s_month.upper() in month_TLA: return 0
	rv = 0
	for tla in month_TLA:
		if s_month.upper() == tla:
			break
		rv += 1
	return rv

def next_month(index):
	if index > 11:
		return 1
	else: return index + 1

def previous_month(index):
	if index < 2:
		return 12
	else: return index - 1

def is_convertable_to_float(input):
	try:
		test_val = float(input)
		return True
	except:
		return False

'''
Imports a CVP ops spreadsheet saved as comma-separated values
Returns a dictionary with keys that match the list of forecast locations in the second argrument
Dictionary values are lists of CSV lines that "belong" to the location named in the key
'''
def import_CVP_Ops_csv(ops_fname, forecast_locations, active_locations):
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
					if not line_contains_months and t.strip().upper() in month_TLA:
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

				if current_location in active_locations and len(token[1].strip()) > 1:
					print("PROFILEDATE: %s"%(token[1]))
					data_lines.append("PROFILEDATE: %s"%(token[1]))
					if DEBUG: print "setting profile date to %s at %s"%(token[1], current_location)
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

'''
Imports a CVP ops spreadsheet saved as XLS or XLSX format
Returns a dictionary with keys that match the list of forecast locations in the second argrument
Dictionary values are lists of CSV lines that "belong" to the location named in the key

Excel formats are decoded by the Apache POI library. See import block at the top of the
file. The instructional web sites below helped with interpreting values from formula cells
https://www.baeldung.com/java-apache-poi-cell-string-value
https://www.baeldung.com/java-read-dates-excel

This script expects to use version 3.8 of the POI library. Newer versions may have API changes.
In particular, look out for SSUsermodel.Cell.CELL_TYPE_XXX, which is a constant in v 3.8, and part
of an enumeration in v 4.X
'''
def import_CVP_Ops_xls(ops_fname, forecast_locations, active_locations, sheet_number=0):
	current_location = None
	start_month = None
	first_date_index = -1
	location_count = 0
	ts_count = 0
	data_lines = []
	rv_dictionary = {}
	calendar = ""

	try:
		if ops_fname.endswith(".xlsx"):
			workbook = XSSFWorkbook(
				java.io.FileInputStream(java.io.File(ops_fname)))
		if ops_fname.endswith(".xls"):
			workbook = HSSFWorkbook(
				java.io.FileInputStream(java.io.File(ops_fname)))
	except Exception as e:
		raise e

	sheet = workbook.getSheetAt(sheet_number)
	formatter = SSUsermodel.DataFormatter(True)
	num_lines = 0; num_data_lines = 0
	for row in sheet.iterator():
		num_lines += 1
		line_contains_months = False
		token = []
		for cell in row.cellIterator():
			# This business -- Cell.CELL_TYPE_XXX -- has been revised a couple of times
			# between POI version 3.8 and 4.x. Watch out it doesn't bite us
			if cell.getCellType() == SSUsermodel.Cell.CELL_TYPE_FORMULA:
				cachedType = cell.getCachedFormulaResultType()
				# print str(cachedType) + " : " + formatter.formatCellValue(cell)
				if cachedType == SSUsermodel.Cell.CELL_TYPE_NUMERIC:
					if SSUsermodel.DateUtil.isCellDateFormatted(cell):
						token.append(monthFromDateStr(str(cell.getDateCellValue())))
					else:
						token.append(str(cell.getNumericCellValue()))
				if cachedType == SSUsermodel.Cell.CELL_TYPE_STRING:
					token.append(str(cell.getStringCellValue()))
			else:
				token.append(formatter.formatCellValue(cell))
		# figure out what columns our data start in, what month we're looking at, and ignore blank lines
		num_t = 0; num_val = 0
		for t in token:
			if len(t.strip()) > 0:
				num_val += 1
				# if there's a month label in the first 6 cells of the row, the row is a calendar line
				if ((not line_contains_months) and
					num_t < 6 and
					t.strip().upper() in month_TLA):
					line_contains_months = True
					first_date_index = num_t
					start_month = t.strip().upper()
					if DEBUG: print "Calendar line %d: "%(num_lines)
					if DEBUG: print "Found \"%s\" in column %d"%(t.strip(), num_t + 1)
					calendar = ','.join(token)
			num_t += 1
		if num_val == 0:
			continue # don't include this row in the result

		if token[0].strip() in forecast_locations and len(calendar) > 0:
			if location_count > 0:
				rv_dictionary[current_location] = data_lines
				data_lines = []
			current_location = token[0].strip()
			if DEBUG: print "setting current location to %s"%(current_location)
			data_lines.append("%d,%s"%(first_date_index, calendar))
			if current_location in active_locations and len(token[1].strip()) > 1:
				data_lines.append("PROFILEDATE: %s"%(token[1]))
				if DEBUG: print "setting profile date to %s at %s"%(token[1], current_location)
			location_count += 1
			calendar = ""
			continue

		if not line_contains_months and num_val > 10:
			data_lines.append(','.join(token))
			ts_count += 1

	rv_dictionary[current_location] = data_lines #
	print "Found %d forecast locations and %d time series in ops file \n\t%s."%(
		location_count, ts_count, ops_fname)
	return rv_dictionary

'''
Converts a row from an operations CSV file and makes it into a TimeSeriesContainer
Assumes:
	Time step = 1 month
	Volumes in TAF
	Flows in CFS
'''
def make_ops_tsc(location_name, start_year, start_month, ts_line, data_type=None, data_units=None, ops_label=None, currentAlternative=None):
	i_year = start_year
	if currentAlternative:
		currentAlternative.addComputeMessage("making a time series at %s starting at %s %d..."%(location_name, start_month, i_year))
		currentAlternative.addComputeMessage("From data line: \"%s\""%(ts_line))
	if DEBUG:
		print "making a time series at %s starting at %s %d..."%(location_name, start_month, i_year)
		print "From data line: \"%s\""%(ts_line)
	param = ""

	if not data_type:
		data_type = "PER-CUM" # "PER-AVER"
	if not data_units:
		data_units = "AC-FT" # "CFS"
	if not ops_label:
		ops_label=""

	i_month = month_index(start_month)
	ts_vals = []
	ts_times = []    #HecTime objects
	ts_minutes = []  #minutes
	t_count = 0
	v_count = 0

	tokens = ts_line.split(',')
	for token in tokens:
		t_count += 1
		if len(token.strip()) == 0:
			# values are in a continuous block of comma-separated values, so a null
			# after we've started adding values means we've reached the last value
			if v_count > 0:
				break
			# a null before we've started adding values means we're still looking for
			# the first value
			continue
		# first non-empty field is the parameter
		try:
			ts_vals.append(float(token.strip()))
			v_count += 1
			if data_units == "AC-FT":
				ts_vals[-1] = ts_vals[-1]*1000. # convert TAF to Acre-Feet
			dateTime = HecTime()
			dateTime.setYearMonthDay(i_year, i_month, get_days_in_month(i_month, i_year), 1440)
			ts_times.append(dateTime)
			last_month = i_month
			i_month = next_month(i_month)
			if (i_month - last_month) < 0:
				i_year += 1
		except ValueError:
			# conversion to float failed, so the token is assumed to be the paramter (C Part)
			# of the time series unless we've already got one
			if len(param) == 0:
				param = token.strip().upper()
				if currentAlternative:
					currentAlternative.addComputeMessage("making a time series of %s at %s ..."%(param, location_name))
				if param.strip(')').endswith("CFS") or param.endswith("AFRP"):
					param = "FLOW-" + param
					data_type = "PER-AVER"
					data_units = "CFS"
				if param.strip(')').endswith("ACRES"):
					data_type = "INST-VAL"
					data_units = "ACRES"
				if param.strip(')').endswith("FEET"):
					data_type = "INST-VAL"
					data_units = "FEET"
				if param.strip(')').endswith("STORAGE"):
					data_type = "INST-VAL"


	# working_math = tsmath.generateRegularIntervalTimeSeries(time_start.date(8), time_end.date(8), "1MON", 1.0)
	# convert HecTimes to minutes
	for dt in ts_times:
		ts_minutes.append(dt.getMinutes())
	rv_tsc = tscont()
	rv_tsc.type = data_type
	rv_tsc.units = data_units
	rv_tsc.numberValues = len(ts_vals)
	rv_tsc.values = ts_vals
	rv_tsc.times = ts_minutes
	rv_tsc.startTime = ts_minutes[0]
	rv_tsc.location = location_name.replace('/', '-')
	rv_tsc.parameter = param.replace('/', '-')
	rv_tsc.interval = 43200
	rv_tsc.version = ops_label
	rv_tsc.fullName = "//%s/%s//1MON/%s/"%(rv_tsc.location,rv_tsc.parameter,rv_tsc.version)

	return rv_tsc

'''
turn monthly volumes into uniform daily average flows
  optional key-word argument specifies the number of days represented by a partial month at the
	beginning of the period the volume has accumulated over
	start_day_count: integer
Assumptions:
	- input time series is either a monthly average of daily flows or a monthly volume in acre-feet
	- a start_day_count of n indicates that the return value is a time series beginning with the last n
	days of the first month in the input time series. An input time series beginning in April, with a
	start-day-count of 14 will result in a daily time series starting at the end of  16 April.
'''
def uniform_transform_monthly_to_daily(tsmath_months, start_day_count=None, currentAlternative=None):
	start_time_in = HecTime(tsmath_months.firstValidDate(), HecTime.MINUTE_INCREMENT)
	end_time_in = HecTime(tsmath_months.lastValidDate(), HecTime.MINUTE_INCREMENT)

	if not start_day_count:
		start_day_count = start_time_in.day()

	#output time series will begin start_day_count days before the end of the first month in the monthly input ts
	start_day_of_month = 1 + get_days_in_month(start_time_in.month(), start_time_in.year()) - start_day_count
	start_time_out = HecTime()
	start_time_out.setYearMonthDay(start_time_in.year(), start_time_in.month(), start_day_of_month, 0)
	print "uniform daily time series start time = " + start_time_out.date(4) + ' ' + str(start_time_out.minutesSinceMidnight())

	# is the input volumes or flows?
	input_is_acrefeet = True
	if tsmath_months.getUnits().upper().startswith("TAF"):
		tsmath_months = tsmath_months.multiply(1000.0)
		tsmath_months.setUnits("AC-FT")
		tsmath_months.setType("PER-CUM")
	elif tsmath_months.getUnits().upper().startswith("CFS"):
		input_is_acrefeet = False

	# get the date and time value lists from the TimeSeriesMath objects
	tsc_months = tsmath_months.getData()

	if currentAlternative:
		currentAlternative.addComputeMessage("Calculating uniform time series for %s at %s"%(tsc_months.parameter, tsc_months.location))
		currentAlternative.addComputeMessage("Input time series starting at %s"%(str(start_time_in)))
		currentAlternative.addComputeMessage("Output time series starting at %s"%(str(start_time_out)))

	elif DEBUG:
		print "Calculating uniform time series for %s at %s"%(tsc_months.parameter, tsc_months.location)
		print "Input time series starting at %s"%(str(start_time_in))
		print "Output time series starting at %s"%(str(start_time_out))

	# create HecTime objects for indexing the pattern and output time series
	search_time = HecTime()
	post_time = HecTime()

	tsc_result = tsmath.generateRegularIntervalTimeSeries(start_time_out.date(8), end_time_in.date(8), "1DAY", "0M", 1.0).getData()
	path_parts = tsc_months.fullName.split('/')
	path_parts[5] = "1DAY"
	tsc_result.fullName = '/'.join(path_parts)
	tsc_result.version = "UNIFORM"
	tsc_result.location = tsc_months.location

	if input_is_acrefeet:
		tsc_result.units = "CFS"
		tsc_result.type = "PER-AVER"
	else:
		tsc_result.units = tsc_months.units
		tsc_result.type = tsc_months.type
		tsc_result.parameter = tsc_months.parameter

	i = 0
	for tm in tsc_result.times:
		post_time.setMinutes(tm)
		# print "post_time = " + post_time.date(4) + ' ' + str(post_time.minutesSinceMidnight())

		cfs_conversion = 1.
		if input_is_acrefeet:
			if tm <= tsc_months.times[0]:
				cfs_conversion = 0.50417/start_day_count
			else:
				cfs_conversion = 0.50417/get_days_in_month(post_time.month(), post_time.year())

		if tm <= tsc_months.times[0]:
			tsc_result.values[i] = tsc_months.values[0]*cfs_conversion
		else:
			search_time.setYearMonthDay(post_time.year(), post_time.month(),
				get_days_in_month(post_time.month(), post_time.year()), 1440)
			tsc_result.values[i] = tsc_months.getValue(search_time)*cfs_conversion

		i += 1

	return tsmath(tsc_result)

'''
turn monthly volumes into uniform hourly average flows
  optional key-word argument specifies the number of days represented by a partial month at the
	beginning of the period the volume has accumulated over
	start_day_count: integer
Assumptions:
	- input time series is either a monthly average of daily flows or a monthly volume in acre-feet
	- a start_day_count of n indicates that the return value is a time series beginning with the last n
	days of the first month in the input time series. An input time series beginning in April, with a
	start-day-count of 14 will result in a daily time series starting on 17 April.
'''
def uniform_transform_monthly_to_hourly(tsmath_months, start_day_count=None, currentAlternative=None):
	start_time_in = HecTime(tsmath_months.firstValidDate(), HecTime.MINUTE_INCREMENT)
	end_time_in = HecTime(tsmath_months.lastValidDate(), HecTime.MINUTE_INCREMENT)

	if not start_day_count:
		start_day_count = start_time_in.day()

	#output time series will begin start_day_count days before the end of the first month in the monthly input ts
	start_day_of_month = 1 + get_days_in_month(start_time_in.month(), start_time_in.year()) - start_day_count
	start_time_out = HecTime()
	start_time_out.setYearMonthDay(start_time_in.year(), start_time_in.month(), start_day_of_month, 0)

	print "hourly start time = " + start_time_out.date(4) + ' ' + str(start_time_out.minutesSinceMidnight())

	# is the input volumes or flows?
	input_is_acrefeet = True
	if tsmath_months.getUnits().upper().startswith("TAF"):
		tsmath_months = tsmath_months.multiply(1000.0)
		tsmath_months.setUnits("AC-FT")
		tsmath_months.setType("PER-CUM")
	elif tsmath_months.getUnits().upper().startswith("CFS"):
		input_is_acrefeet = False

	# get the date and time value lists from the TimeSeriesMath objects
	tsc_months = tsmath_months.getData()

	if currentAlternative:
		currentAlternative.addComputeMessage("Calculating uniform time series for %s at %s"%(tsc_months.parameter, tsc_months.location))
		currentAlternative.addComputeMessage("Input time series starting at %s"%(str(start_time_in)))
		currentAlternative.addComputeMessage("Output time series starting at %s"%(str(start_time_out)))

	elif DEBUG:
		print "Calculating uniform time series for %s at %s"%(tsc_months.parameter, tsc_months.location)
		print "Input time series starting at %s"%(str(start_time_in))
		print "Output time series starting at %s"%(str(start_time_out))

	# create HecTime objects for indexing the pattern and output time series
	search_time = HecTime()
	post_time = HecTime()

	tsc_result = tsmath.generateRegularIntervalTimeSeries(start_time_out.date(8), end_time_in.date(8), "1HOUR", "0M", 1.0).getData()
	path_parts = tsc_months.fullName.split('/')
	path_parts[5] = "1HOUR"
	tsc_result.fullName = '/'.join(path_parts)
	tsc_result.version = "UNIFORM"
	tsc_result.location = tsc_months.location

	if input_is_acrefeet:
		tsc_result.units = "CFS"
		tsc_result.type = "PER-AVER"
	else:
		tsc_result.units = tsc_months.units
		tsc_result.type = tsc_months.type
		tsc_result.parameter = tsc_months.parameter

	i = 0
	for tm in tsc_result.times:
		post_time.setMinutes(tm)
		# print "post_time = " + post_time.date(4) + ' ' + str(post_time.minutesSinceMidnight())

		cfs_conversion = 1.
		if input_is_acrefeet:
			if tm <= tsc_months.times[0]:
				cfs_conversion = 0.50417/start_day_count
			else:
				cfs_conversion = 0.50417/get_days_in_month(post_time.month(), post_time.year())

		if tm <= tsc_months.times[0]:
			tsc_result.values[i] = tsc_months.values[0]*cfs_conversion
		else:
			search_time.setYearMonthDay(post_time.year(), post_time.month(),
				get_days_in_month(post_time.month(), post_time.year()), 1440)
			tsc_result.values[i] = tsc_months.getValue(search_time)*cfs_conversion

		i += 1

	return tsmath(tsc_result)

'''
turn monthly volumes into daily average flows according to an annual pattern
Assumptions:
	pattern time series covers a calendar year
	pattern time series year is not a leap year (year 3000 is OK)
	pattern time and output time series are daily average flows in CFS
	input time series is either a monthly average of daily flows or a monthly volume in acre-feet
'''
def weight_transform_monthly_to_daily(tsmath_months, tsmath_pattern, start_day_count=None, currentAlternative=None):
	start_time_in = HecTime(tsmath_months.firstValidDate(), HecTime.MINUTE_INCREMENT)
	end_time_in = HecTime(tsmath_months.lastValidDate(), HecTime.MINUTE_INCREMENT)
	start_time_pattern = HecTime(tsmath_pattern.firstValidDate(), HecTime.MINUTE_INCREMENT)

	if not start_day_count:
		start_day_count = start_time_in.day()

	#output time series will begin start_day_count days before the end of the first month in the monthly input ts
	start_day_of_month = 1 + get_days_in_month(start_time_in.month(), start_time_in.year()) - start_day_count
	start_time_out = HecTime()
	start_time_out.setYearMonthDay(start_time_in.year(), start_time_in.month(), start_day_of_month, 0)

	# is the input volumes or flows?
	input_is_acrefeet = True
	if tsmath_months.getUnits().upper().startswith("TAF"):
		tsmath_months = tsmath_months.multiply(1000.0)
		tsmath_months.setUnits("AC-FT")
		tsmath_months.setType("PER-CUM")
	elif tsmath_months.getUnits().upper().startswith("CFS"):
		input_is_acrefeet = False

	# calculate monthly average daily flows from the daily flow pattern time series
	tsmath_pattern_ave = tsmath_pattern.transformTimeSeries("1MON", "", "AVE")

	# get the date and time value lists from the TimeSeriesMath objects
	tsc_months = tsmath_months.getData()
	tsc_pattern = tsmath_pattern.getData()
	tsc_pattern_ave = tsmath_pattern_ave.getData()

	if currentAlternative:
		currentAlternative.addComputeMessage("Calculating weighted time series for %s at %s"%(tsc_months.parameter, tsc_months.location))
		currentAlternative.addComputeMessage("Input time series starting at %s"%(str(start_time_in)))
		currentAlternative.addComputeMessage("Output time series starting at %s"%(str(start_time_out)))
	elif DEBUG:
		print "Calculating weighted time series for %s at %s"%(tsc_months.parameter, tsc_months.location)
		print "Input time series starting at %s"%(str(start_time_in))
		print "Output time series starting at %s"%(str(start_time_out))

	# create HecTime objects for indexing the pattern and output time series
	search_time = HecTime()
	post_time = HecTime()

	# Make a dictionary of volume ratios by month (i.e. this month's volume/pattern year volume for month)
	scale_lookup = {}
	in_time = HecTime( HecTime.MINUTE_INCREMENT)
	for time_int in tsc_months.times:
		in_time.set(time_int)
		print "Input date: %d %s %d (%d)"%(in_time.day(), month_TLA[in_time.month()], in_time.year(), time_int)
		search_time.setYearMonthDay(start_time_pattern.year(), in_time.month(), days_in_month[in_time.month()], 1440)

		key = in_time.year()*100+in_time.month()

		if input_is_acrefeet:
			scale_lookup[key] = tsc_months.getValue(in_time)*0.50417/days_in_month[in_time.month()]/tsc_pattern_ave.getValue(search_time)
		else:
			scale_lookup[key] = tsc_month.getValue(in_time)/tsc_pattern_ave.getValue(search_time)

		if currentAlternative:
			currentAlternative.addComputeMessage("scale for %s %d = %f"%(month_TLA[in_time.month()], in_time.year(), scale_lookup[in_time.month()]))
		elif DEBUG:
			print "scale for %s %d = %f"%(month_TLA[in_time.month()], in_time.year(), scale_lookup[key])

	# if we're starting mid-month, recalculate acre-feet scale factor for the first month
	if input_is_acrefeet and start_day_of_month > 1:
		first_month_key = start_time_in.year()*100 + start_time_in.month()
		sum_flows = 0.0
		i = 0
		search_time.setYearMonthDay(start_time_pattern.year(), start_time_in.month(), start_day_of_month, 1440)
		first_month = search_time.month()
		if DEBUG: print "Starting pattern time series at %s"%search_time.date(4)
		while search_time.month() == first_month:
			sum_flows += tsc_pattern.getValue(search_time)
			i += 1
			print "index = %d"%(i)
			search_time.addDays(1)
		scale_lookup[first_month_key] = tsc_months.values[0]*0.50417 / sum_flows
		if DEBUG: print "{}AF/{}cfs-day = {}".format(tsc_months.values[0], sum_flows, scale_lookup[first_month_key])

	# if we're starting first-of-month, duplicate acre-feet scale factor for the first month to the previous month
	if input_is_acrefeet and start_day_of_month == 1:
		key = 0
		if start_time_in.month() == 1:
			key = (start_time_in.year() - 1)*100 + 12
		else:
			key = start_time_in.year()*100 + start_time_in.month() - 1
		first_month_key = start_time_in.year()*100 + start_time_in.month()
		scale_lookup[key] = scale_lookup[first_month_key]

	tsc_result = tsmath.generateRegularIntervalTimeSeries(start_time_out.date(8), end_time_in.date(8), "1DAY", "0M", 1.0).getData()
	tsc_result.fullName = tsc_months.fullName
	tsc_result.units = "CFS"
	tsc_result.type = "PER-AVER"

	i = 0
	for time_min in tsc_result.times:
		post_time.setMinutes(time_min)
		search_time.setYearMonthDay(start_time_pattern.year(), post_time.month(), post_time.day(), 1440)
		scale = scale_lookup[post_time.month()+100*post_time.year()]
		tsc_result.values[i] = scale * tsc_pattern.getValue(search_time)
		i += 1
	tsm_result = tsmath(tsc_result)
	tsm_result.setVersion("WEIGHTED")
	print "Weight disaggregation of %s complete."%(tsc_result.fullName)
	return tsm_result

'''
returns a list of TimeSeriesMath objects.
names_weights is a python dictionary of "location name":weight
weights are normalized at compute time
'''
def split_time_series_static(tsmath_in, names_weights, out_param_name):
	rv_tsmath_list = []

	total_weight = 0.
	for key in names_weights.keys():
		total_weight += names_weights[key]

	for key in names_weights:
		tsmath_product = tsmath_in.multiply(names_weights[key]/total_weight)
		tsmath_product.setParameterPart(out_param_name)
		tsmath_product.setLocation(key)
		rv_tsmath_list.append(tsmath_product)

	return rv_tsmath_list

'''
returns a list of TimeSeriesMath objects.
names_weights is a python dictionary of "location name":(tuple of 12 weights-by-month Jan-Dec)
weights are normalized at compute time
'''
def split_time_series_monthly(tsmath_in, names_weights, out_param_name):
	rv_tsmath_list = []

	total_weight = []
	for i in range(12):
		month_sum = 0
		for key in names_weights.keys():
			month_sum += names_weights[key][i]
		total_weight.append(month_sum)

	time_start = HecTime(tsmath_in.firstValidDate(), HecTime.MINUTE_INCREMENT)
	time_end = HecTime(tsmath_in.lastValidDate(), HecTime.MINUTE_INCREMENT)
	weight_container = tsmath.generateRegularIntervalTimeSeries(
		time_start.date(8), time_end.date(8), "1DAY", "0M", 1.0).getData()

	for key in names_weights.keys():
		for i in range(weight_container.numberValues):
			time_end.set(weight_container.times[i])
			weight_container.values[i] = names_weights[key][time_end.month() - 1]/total_weight[time_end.month() - 1]
		weight_math = tsmath(weight_container)
		tsmath_product = tsmath_in.multiply(weight_math)
		tsmath_product.setParameterPart(out_param_name)
		tsmath_product.setLocation(key)
		rv_tsmath_list.append(tsmath_product)
	return rv_tsmath_list

'''
Backward moving average
Because DSSMath doesn't have a function for this...
'''
def backwardsMovingAverage(tsmath_in, num_periods):
	rv_tsc = tsmath_in.getData() # getData() returns a copy of the tsMath's time-series container
	rv_parts = rv_tsc.fullName.strip('/').split('/')
	i = 0; j = 0
	in_vals = tsmath_in.getContainer().values # getContainer() returns access to the time-series container in place
	if DEBUG:
		print "Input TSMath for moving average contains %d values."%(tsmath_in.getContainer().numberValues)
	out_vals =[]
	for val in in_vals:
		j += 1
		k = j - num_periods
		moving_sum = 0.
		moving_count = 0.
		if k < 0: k = 0
		for addend in in_vals[k:j]:
			if addend == hec.lang.Const.UNDEFINED_DOUBLE:
				continue
			else:
				moving_sum += addend
				moving_count += 1.0
		out_vals.append(moving_sum/moving_count)
		i += 1

	if DEBUG:
		print "Result TSMath for moving average contains %d values."%(len(out_vals))
	rv_tsc.values = out_vals
	rv_tsc.fullName = "//test/flow-avg//" + rv_parts[-2] + "/moving/"
	return tsmath(rv_tsc)


'''
temp_regression_coefficients is a dictionary
	key = location name
	value = tuple (Intercept (deg C), Flow Coef (cfs), Air Temp Coef (deg C), RMS Error (deg C)

Steve's notes on the regression:
	Flow needs to be averaged with a 7 day centered average first
	Air temp needs to be averaged with a 7 day centered average first
	Flow is in cfs
	Air temp is in deg C
	Resulting water temp is in deg C
'''
def evaluate_temp_regression(tsmath_flow, tsmath_airtemp, temp_regression_coefficients, currentAlternative = None):
	if currentAlternative: currentAlternative.addComputeMessage("Calculating water temperatures at %s..."%(tsmath_flow.getContainer().location))
	if tsmath_flow.isMetric():
		if currentAlternative: currentAlternative.addComputeMessage("Flow units were \"%s\.\""%(tsmath_flow.getUnits()))
		tsmath_flow = tsmath_flow.convertToEnglishUnits()
		if currentAlternative: currentAlternative.addComputeMessage("Flow units converted to \"%s\.\""%(tsmath_flow.getUnits()))
	if tsmath_airtemp.isEnglish():
		if currentAlternative: currentAlternative.addComputeMessage("Temperature units were \"%s\.\""%(tsmath_airtemp.getUnits()))
		tsmath_airtemp = tsmath_airtemp.convertToMetricUnits()
		if currentAlternative: currentAlternative.addComputeMessage("Temperature units converted to \"%s\.\""%(tsmath_airtemp.getUnits()))

	if DEBUG: print "Calculating temperatures at %s"%(tsmath_flow.getContainer().location)
	tsmath_airtemp = tsmath_airtemp.transformTimeSeries("1DAY", "", "AVE")
	if "F" in tsmath_airtemp.getUnits().upper():
		if DEBUG: print "Converting temperatures at %s to Celsius."%(tsmath_flow.getContainer().location)
		tsmath_airtemp.setUnits("deg F")
		tsmath_airtemp = tsmath_airtemp.convertToMetricUnits()
	if "C" in tsmath_airtemp.getUnits().upper():
		tsmath_airtemp.setUnits("deg C")
	if DEBUG: print "\tApplying flows..."
	tsmath_watertemp = tsmath_flow.centeredMovingAverage(7, False, True).multiply(temp_regression_coefficients[1])
	tsmath_watertemp.setUnits("deg C")
	if DEBUG: print "\tApplying air temperature..."
	tsmath_watertemp = tsmath_watertemp.add(tsmath_airtemp.centeredMovingAverage(7, False, True).multiply(temp_regression_coefficients[2]))
	if DEBUG: print "\tApplying constant..."
	tsmath_watertemp = tsmath_watertemp.add(temp_regression_coefficients[0])
	start_time = HecTime(tsmath_airtemp.firstValidDate(), HecTime.MINUTE_INCREMENT)
	start_time.setTime("0000")
	end_time = HecTime(tsmath_airtemp.lastValidDate(), HecTime.MINUTE_INCREMENT)
	# print "Starts at " + start_time.dateAndTime(4)
	# print "Ends at " + end_time.dateAndTime(4)
	tsmath_out = tsmath.generateRegularIntervalTimeSeries(start_time.dateAndTime(4), end_time.dateAndTime(4), "1HOUR", "", 0.0)
	tsmath_out.setUnits("deg C")
	tsmath_out = tsmath_watertemp.transformTimeSeries(tsmath_out, "INT")
	tsmath_out.setParameterPart("TEMP-WATER")

	return tsmath_out

def leapYearTest(currentAlternative):
	test = HecTime(HecTime.MINUTE_INCREMENT)
	test.setYearMonthDay(3000, 2, 28, 1440)
	currentAlternative.addComputeMessage("HecTime 28 Feb 3000 = %d"%(test.getMinutes()))
	test.setYearMonthDay(3000, 2, 29, 1440)
	currentAlternative.addComputeMessage("HecTime 29 Feb 3000 = %d"%(test.getMinutes()))
	test.setYearMonthDay(3000, 3, 1, 1440)
	currentAlternative.addComputeMessage("HecTime 1 Mar 3000 = %d"%(test.getMinutes()))
	return
