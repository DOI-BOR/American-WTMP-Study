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
	"""Return the number of days in a given month, accounting for leap years.

	Parameters
	----------
	month_int : int
		Calendar month, 1-12.
	year_int : int
		Calendar year, used only to resolve February's length in leap years.

	Returns
	-------
	int
		Number of days in the given month/year.

	Raises
	------
	ValueError
		If ``month_int`` is outside the range 1-12.
	"""
	if month_int > 12 or month_int < 1:
		raise ValueError("Month (%d) is not an int between 1 and 12."%(month_int))
	if month_int == 2 and HecTime.isLeap(year_int):
		return 29
	return days_in_month[month_int]

def month_index(s_month):
	"""Look up the 1-based month number for a three-letter month abbreviation.

	Parameters
	----------
	s_month : str
		Three-letter month abbreviation (case-insensitive), matched against
		the module-level ``month_TLA`` list.

	Returns
	-------
	int
		Month index matching the position of ``s_month`` in ``month_TLA``
		(1-12 for JAN-DEC), or 0 if ``s_month`` is not a recognized
		abbreviation (including the placeholder "NM" entry at index 0).
	"""
	if not s_month.upper() in month_TLA: return 0
	rv = 0
	for tla in month_TLA:
		if s_month.upper() == tla:
			break
		rv += 1
	return rv

def next_month(index):
	"""Return the month number following the given month, wrapping December to January.

	Parameters
	----------
	index : int
		Current month number, 1-12.

	Returns
	-------
	int
		Next month number; wraps from 12 back to 1.
	"""
	if index > 11:
		return 1
	else: return index + 1

def previous_month(index):
	"""Return the month number preceding the given month, wrapping January to December.

	Parameters
	----------
	index : int
		Current month number, 1-12.

	Returns
	-------
	int
		Previous month number; wraps from 1 (or below) back to 12.

	Notes
	-----
	The wrap condition is ``index < 2``, so any index of 1 or less (including
	0, the "NM" placeholder returned by month_index for unrecognized input)
	is treated as wrapping to December.
	"""
	if index < 2:
		return 12
	else: return index - 1

def is_convertable_to_float(input):
	"""Check whether a value can be converted to a Python float.

	Parameters
	----------
	input : object
		Value to test, typically a string token from a spreadsheet cell.

	Returns
	-------
	bool
		True if ``float(input)`` succeeds, False otherwise.
	"""
	try:
		test_val = float(input)
		return True
	except:
		return False

def import_CVP_Ops_csv(ops_fname, forecast_locations, active_locations):
	"""Import a CVP operations spreadsheet saved as comma-separated values.

	Parameters
	----------
	ops_fname : str
		Path to the CSV file exported from the CVP operations spreadsheet.
	forecast_locations : list of str
		Location names recognized as section headers within the CSV.
	active_locations : list of str
		Subset of ``forecast_locations`` for which a PROFILEDATE marker row
		is extracted and recorded, if present.

	Returns
	-------
	dict
		Dictionary keyed by entries from ``forecast_locations`` that were
		found in the file. Each value is a list of CSV data lines belonging
		to that location, with the calendar header line prefixed by its
		starting column index (see the leading line format below) and, for
		active locations, a "PROFILEDATE: ..." marker line if found.

	Notes
	-----
	Column scanning is limited to the first 26 columns (``token[:26]``)
	because the sample spreadsheet this was built against had an unused
	summary block starting at column AA; that block is intentionally
	ignored rather than parsed.
	"""
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

			# A line whose first field matches a known forecast location (and
			# that follows a calendar line) starts a new location section;
			# flush the previous location's accumulated data lines first.
			if token[0].strip() in forecast_locations and len(calendar) > 0:
				if location_count > 0:
					rv_dictionary[current_location] = data_lines
				data_lines = []
				current_location = token[0].strip()
				print "setting current location to %s"%(current_location)
				data_lines.append("%d,%s"%(first_date_index, calendar.strip()))

				# Active locations additionally carry a profile-date marker
				# in the second field, if present, used downstream to align
				# the operations data to a specific starting date.
				if current_location in active_locations and len(token[1].strip()) > 1:
					print("PROFILEDATE: %s"%(token[1]))
					data_lines.append("PROFILEDATE: %s"%(token[1]))
					if DEBUG: print "setting profile date to %s at %s"%(token[1], current_location)
				location_count += 1
				calendar = ""
				continue

			# Non-calendar, non-header lines are treated as time-series data
			# rows belonging to the current location.
			if not line_contains_months:
				data_lines.append(line.strip())
				ts_count += 1

	rv_dictionary[current_location] = data_lines #
	print "Found %d forecast locations and %d time series in ops file \n\t%s."%(
		location_count, ts_count, ops_fname)
	return rv_dictionary


def monthFromDateStr(str):
	"""Extract a three-letter month abbreviation from a date-like string.

	Parameters
	----------
	str : str
		Whitespace-separated string expected to contain a recognizable
		three-letter month abbreviation token (e.g. a Java date's toString
		output).

	Returns
	-------
	str or None
		The matching month abbreviation in upper case, or ``None`` if no
		token in the string matches a recognized abbreviation.

	Notes
	-----
	Defines its own local ``month_TLA`` list identical to the module-level
	one rather than referencing it directly; this is redundant but
	harmless, and is preserved rather than simplified.
	"""
	month_TLA = ["NM", "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
	for token in str.split():
		if token.strip().upper() in month_TLA:
			return token.strip().upper()
	return None

def excel_date_str_2_dmy(date_str):
	"""Convert an Excel-derived date string into day-month-year form.

	Parameters
	----------
	date_str : str
		Date string either in Java ``Date.toString()`` form (e.g.
		``"Wed Jan 01 00:00:00 PST 2025"``) or slash-delimited numeric form
		(e.g. ``"1/1/2025"``).

	Returns
	-------
	str
		Date formatted as ``DD-MON-YYYY`` (e.g. ``"1-JAN-2025"``).

	Notes
	-----
	Only two input formats are handled (a 6-token Java toString format and a
	3-token slash-delimited format); other formats silently fall through
	and the function returns ``None`` implicitly.
	"""
	if DEBUG: print "Excel date: " + date_str
	parts = date_str.split()
	if len(parts) == 6:
		return parts[2] + '-' + parts[1].upper() + '-' + parts[5]
	parts = date_str.split('/')
	if len(parts) == 3:
		return parts[1] + '-' + month_TLA[int(parts[0])] + '-' + parts[2]

def import_CVP_Ops_xls(ops_fname, forecast_locations, active_locations, sheet_number=0):
	"""Import a CVP operations spreadsheet saved as XLS or XLSX format.

	Parameters
	----------
	ops_fname : str
		Path to the Excel workbook (``.xls`` or ``.xlsx``).
	forecast_locations : list of str
		Location names recognized as section headers within the sheet.
	active_locations : list of str
		Subset of ``forecast_locations`` for which a PROFILEDATE marker row
		is extracted and recorded, if present.
	sheet_number : int, optional
		Zero-based index of the worksheet to read. Defaults to 0.

	Returns
	-------
	dict
		Dictionary keyed by entries from ``forecast_locations`` that were
		found in the sheet. Each value is a list of comma-joined data lines
		belonging to that location, with the calendar header line prefixed
		by its starting column index, and for active locations, a
		"PROFILEDATE: ..." marker line if found.

	Notes
	-----
	Excel formats are decoded by the Apache POI library (see the import
	block at the top of this file). This script expects POI version 3.8;
    newer versions may have API changes, particularly around
    ``SSUsermodel.Cell.CELL_TYPE_XXX``, which is a constant in v3.8 but part
    of an enumeration in v4.x. Calendar-row detection only scans the first
    6 cells of a row (``num_t < 6``), unlike the CSV importer's 26-column
    scan window; this asymmetry is preserved as-is rather than aligned.
	"""
	current_location = None
	start_month = None
	first_date_index = -1
	location_count = 0
	ts_count = 0
	data_lines = []
	rv_dictionary = {}
	calendar = ""

	# Select the appropriate POI workbook reader based on file extension.
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
		num_cols = 0
		line_contains_months = False
		token = []
		for cell in row.cellIterator():
			# This business -- Cell.CELL_TYPE_XXX -- has been revised a couple of times
			# between POI version 3.8 and 4.x. Watch out it doesn't bite us
			cellType = cell.getCellType()
			if cellType == SSUsermodel.Cell.CELL_TYPE_FORMULA:
				# Formula cells must be read via their cached result type
				# rather than their nominal cell type.
				cachedType = cell.getCachedFormulaResultType()
				print str(cachedType) + " : " + formatter.formatCellValue(cell)
				if cachedType == SSUsermodel.Cell.CELL_TYPE_NUMERIC:
					if SSUsermodel.DateUtil.isCellDateFormatted(cell):
						# calendar rows have month labels starting in column 2
						if num_cols > 1:
							token.append(monthFromDateStr(str(cell.getDateCellValue())))
						else:
							token.append(str(cell.getDateCellValue()))
					else:
						token.append(str(cell.getNumericCellValue()))
				if cachedType == SSUsermodel.Cell.CELL_TYPE_STRING:
					token.append(str(cell.getStringCellValue()))
			else:
				# Non-formula cells are read directly according to their
				# declared cell type.
				if cellType == SSUsermodel.Cell.CELL_TYPE_STRING:
					token.append(str(cell.getStringCellValue()))
				elif cellType == SSUsermodel.Cell.CELL_TYPE_NUMERIC:
					if SSUsermodel.DateUtil.isCellDateFormatted(cell):
						# calendar rows have month labels starting in column 2
						if num_cols > 1:
							token.append(monthFromDateStr(str(cell.getDateCellValue())))
						else:
							token.append(str(cell.getDateCellValue()))
					else:
						token.append(str(cell.getNumericCellValue()))
				else:
					token.append(formatter.formatCellValue(cell))
			num_cols += 1
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

		# A row whose first field matches a known forecast location (and
		# that follows a calendar row) starts a new location section;
		# flush the previous location's accumulated data lines first.
		if token[0].strip() in forecast_locations and len(calendar) > 0:
			if location_count > 0:
				rv_dictionary[current_location] = data_lines
				data_lines = []
			current_location = token[0].strip()
			if DEBUG: print "setting current location to %s"%(current_location)
			print "%d,%s"%(first_date_index, calendar)
			data_lines.append("%d,%s"%(first_date_index, calendar))
			if current_location in active_locations and len(token[1].strip()) > 1:
				data_lines.append("PROFILEDATE: %s"%(excel_date_str_2_dmy(token[1])))
				if DEBUG: print "setting profile date to %s at %s"%(excel_date_str_2_dmy(token[1]), current_location)
			location_count += 1
			calendar = ""
			continue

		# Non-calendar rows with more than 10 populated cells are treated as
		# time-series data rows for the current location; sparser rows are
		# assumed to be incidental/blank and are skipped.
		if not line_contains_months and num_val > 10:
			data_lines.append(','.join(token))
			ts_count += 1

	rv_dictionary[current_location] = data_lines #
	print "Found %d forecast locations and %d time series in ops file \n\t%s."%(
		location_count, ts_count, ops_fname)
	return rv_dictionary

def make_ops_tsc(location_name, start_year, start_month, ts_line, data_type=None, data_units=None, ops_label=None, currentAlternative=None):
	"""Convert a row from an operations CSV/XLS file into a TimeSeriesContainer.

	Parameters
	----------
	location_name : str
		Location name assigned to the resulting series; any ``/`` is
		replaced with ``-`` for DSS pathname compatibility.
	start_year : int
		Calendar year of the first value in ``ts_line``.
	start_month : str
		Three-letter abbreviation of the first value's calendar month.
	ts_line : str
		Comma-separated data row containing a parameter label token
		followed by a contiguous block of numeric values.
	data_type : str, optional
		DSS data type (e.g. "PER-CUM", "PER-AVER"). Defaults to "PER-CUM"
		and may be overridden based on the detected parameter name.
	data_units : str, optional
		DSS units (e.g. "AC-FT", "CFS"). Defaults to "AC-FT" and may be
		overridden based on the detected parameter name.
	ops_label : str, optional
		Version (F-part) label applied to the resulting series. Defaults to
		an empty string.
	currentAlternative : object, optional
		HEC-ResSim alternative object used for logging compute messages, if
		provided.

	Returns
	-------
	TimeSeriesContainer
		Monthly time series container populated with the parsed values,
		dates, units, type, location, parameter, and version.

	Notes
	-----
	Time step is assumed to be 1 month. Values are assumed to represent
	volumes in TAF unless the detected parameter name indicates flow (CFS),
	acreage, feet, or storage, in which case ``data_type``/``data_units``
	are adjusted accordingly. When units are "AC-FT", parsed values are
    multiplied by 1000 to convert from TAF to acre-feet. Monthly dates are
    stamped at end-of-month, 2400 hours (``get_days_in_month(...)``,
    1440 minutes).
	"""
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

	# Walk the comma-separated tokens: the first non-numeric token is taken
	# as the parameter label (C-part), and the contiguous run of numeric
	# tokens that follows is taken as the monthly value sequence.
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
				# Infer DSS type/units from suffixes in the detected
				# parameter name, overriding the function's defaults.
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

def uniform_transform_monthly_to_daily(tsmath_months, start_day_count=None, currentAlternative=None):
	"""Turn monthly volumes or averages into uniform daily average flows.

	Parameters
	----------
	tsmath_months : TimeSeriesMath
		Monthly time series, either a monthly average of daily flows or a
		monthly volume in TAF/acre-feet.
	start_day_count : int, optional
		Number of days represented by a partial first month. If omitted,
		defaults to the day-of-month of the series' first valid date.
	currentAlternative : object, optional
		HEC-ResSim alternative object used for logging compute messages, if
		provided; otherwise messages are printed when DEBUG is set.

	Returns
	-------
	TimeSeriesMath
		Daily time series spanning from ``start_day_count`` days before the
		end of the first input month through the end of the last input
		month.

	Notes
	-----
	A ``start_day_count`` of n indicates that the output begins with the
	last n days of the first month in the input series; for example, an
	input series beginning in April with ``start_day_count=14`` produces a
	daily series starting at the end of 16 April. Units starting with
	"TAF" are first converted to acre-feet (x1000) and treated as
	cumulative monthly volumes; units of CFS, "DEG", or single-letter "F"/
	"C" are treated as already-averaged quantities rather than volumes to
	disaggregate.
	"""
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
	elif (tsmath_months.getUnits().upper().startswith("CFS") or
		tsmath_months.getUnits().upper().startswith("DEG") or
		(len(tsmath_months.getUnits().upper().strip()) == 1 and
		(tsmath_months.getUnits().upper() == "F" or 
		tsmath_months.getUnits().upper() == "C"))):
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

	# Build the output daily grid and carry over location/path metadata,
	# retargeting the DSS E-part to 1DAY.
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

	# For each output day, look up the governing month's value and convert
	# acre-feet volumes to a uniform CFS rate (0.50417 = acre-ft per
	# cfs-day); non-volume inputs are passed through unconverted.
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

def uniform_transform_monthly_to_hourly(tsmath_months, start_day_count=None, currentAlternative=None):
	"""Turn monthly volumes or averages into uniform hourly average flows.

	Parameters
	----------
	tsmath_months : TimeSeriesMath
		Monthly time series, either a monthly average of daily flows or a
		monthly volume in TAF/acre-feet.
	start_day_count : int, optional
		Number of days represented by a partial first month. If omitted,
		defaults to the day-of-month of the series' first valid date.
	currentAlternative : object, optional
		HEC-ResSim alternative object used for logging compute messages, if
		provided; otherwise messages are printed when DEBUG is set.

	Returns
	-------
	TimeSeriesMath
		Hourly time series spanning from ``start_day_count`` days before the
		end of the first input month through the end of the last input
		month.

	Notes
	-----
	Structurally parallel to uniform_transform_monthly_to_daily but
	produces an hourly grid. A start_day_count of n indicates the output
	begins on the (n+1)th-from-last day of the first input month; for
	example, an input series beginning in April with start_day_count=14
	results in a series starting on 17 April. Unlike the daily version,
    only CFS (not "DEG" or single-letter F/C) is checked to short-circuit
    the acre-feet conversion; this narrower unit check is preserved as-is.
	"""
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

	# Build the output hourly grid and carry over location/path metadata,
	# retargeting the DSS E-part to 1HOUR.
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

	# For each output hour, look up the governing month's value and convert
	# acre-feet volumes to a uniform CFS rate (0.50417 = acre-ft per
	# cfs-day); non-volume inputs are passed through unconverted.
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

def weight_transform_monthly_to_daily(tsmath_months, tsmath_pattern, start_day_count=None, currentAlternative=None):
	"""Disaggregate monthly volumes to daily flows using an annual pattern shape.

	Parameters
	----------
	tsmath_months : TimeSeriesMath
		Monthly time series, either a monthly average of daily flows or a
		monthly volume in TAF/acre-feet.
	tsmath_pattern : TimeSeriesMath
		Daily average flow (CFS) pattern time series covering a calendar
		year, used to shape the within-month daily distribution.
	start_day_count : int, optional
		Number of days represented by a partial first month. If omitted,
		defaults to the day-of-month of the monthly series' first valid
		date.
	currentAlternative : object, optional
		HEC-ResSim alternative object used for logging compute messages, if
		provided; otherwise messages are printed when DEBUG is set.

	Returns
	-------
	TimeSeriesMath
		Daily CFS time series disaggregated according to the pattern
		series' relative daily shape within each month, scaled so each
		month's total matches the corresponding input monthly value.

	Notes
	-----
	Assumes the pattern time series covers a calendar year, is not a leap
	year (year 3000 is used internally as a leap-year-free reference), and
	is itself daily-average CFS. For each input month, a scale factor is
	computed as (that month's volume or average) divided by (the pattern's
	average for the same calendar month), then applied day-by-day to the
	pattern shape. Special handling is included for a partial first month
	(recomputing the scale using the actual sub-month pattern sum) and for
	a series that starts exactly on day 1 (which borrows the first month's
	scale factor for the preceding month, since no partial-month
	adjustment is otherwise available for it).
	"""
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

		# NOTE: the non-acre-feet branch below references "tsc_month"
		# (singular), which is not defined anywhere in this function; this
		# appears to be a pre-existing typo for "tsc_months" and would raise
		# a NameError if ever reached with non-acre-feet input units. It is
		# preserved exactly rather than corrected, per documentation policy.
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

	# Build the output daily series by applying each day's governing
	# monthly scale factor to the pattern series' value for that day.
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

def split_time_series_static(tsmath_in, names_weights, out_param_name):
	"""Split a time series into multiple locations using fixed (non-seasonal) weights.

	Parameters
	----------
	tsmath_in : TimeSeriesMath
		Source time series to be split.
	names_weights : dict
		Dictionary mapping output location name to a numeric weight. Weights
		are normalized (divided by their sum) at compute time, so they need
		not sum to 1.
	out_param_name : str
		Parameter name assigned to each output series.

	Returns
	-------
	list of TimeSeriesMath
		One time series per key in ``names_weights``, each equal to
		``tsmath_in`` multiplied by that location's normalized weight, with
		location and parameter metadata set accordingly.
	"""
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

def split_time_series_monthly(tsmath_in, names_weights, out_param_name):
	"""Split a time series into multiple locations using month-varying weights.

	Parameters
	----------
	tsmath_in : TimeSeriesMath
		Source time series to be split.
	names_weights : dict
		Dictionary mapping output location name to a tuple of 12
		weights-by-month (January through December). Weights are
		normalized across all locations for each month at compute time.
	out_param_name : str
		Parameter name assigned to each output series.

	Returns
	-------
	list of TimeSeriesMath
		One time series per key in ``names_weights``, each equal to
		``tsmath_in`` multiplied by a day-by-day weight series built from
		that location's month-specific normalized fraction, with location
		and parameter metadata set accordingly.

	Notes
	-----
	Normalization sums each month's weight across all locations in
	``names_weights`` so that, for any given day, the split series across
	all returned locations reconstruct the original input when summed.
	"""
	rv_tsmath_list = []

	# Precompute, for each calendar month, the sum of weights across all
	# locations, used to normalize each location's share below.
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

	# For each output location, build a daily weight series (each day's
	# value is that location's normalized fraction for its calendar month)
	# and multiply it against the source series.
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

def backwardsMovingAverage(tsmath_in, num_periods):
	"""Compute a backward-looking (trailing) moving average.

	Parameters
	----------
	tsmath_in : TimeSeriesMath
		Source time series to average.
	num_periods : int
		Number of periods (including the current one) included in each
		trailing average window.

	Returns
	-------
	TimeSeriesMath
		Time series of the same length as ``tsmath_in``, where each value
		is the average of up to ``num_periods`` preceding values (fewer at
		the start of the series, where the window is truncated).

	Notes
	-----
	Implemented manually because the underlying DSSMath library does not
	provide a trailing/backward moving-average function directly. Values
	equal to ``hec.lang.Const.UNDEFINED_DOUBLE`` are excluded from both the
	sum and the count within each window, so the average reflects only
	defined values in range.
	"""
	rv_tsc = tsmath_in.getData() # getData() returns a copy of the tsMath's time-series container
	rv_parts = rv_tsc.fullName.strip('/').split('/')
	i = 0; j = 0
	in_vals = tsmath_in.getContainer().values # getContainer() returns access to the time-series container in place
	if DEBUG:
		print "Input TSMath for moving average contains %d values."%(tsmath_in.getContainer().numberValues)
	out_vals =[]

	# Build each output value as the average of the trailing window
	# [j - num_periods, j), skipping undefined values in both the sum and
	# the count; the window is truncated (not padded) near the series start.
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


def evaluate_temp_regression(tsmath_flow, tsmath_airtemp, temp_regression_coefficients, currentAlternative = None):
	"""Estimate water temperature from flow and air-temperature regressors.

	Parameters
	----------
	tsmath_flow : TimeSeriesMath
		Flow time series used by the regression; converted to English units
		(CFS) internally if supplied in metric units.
	tsmath_airtemp : TimeSeriesMath
		Air-temperature time series used by the regression; converted to
		metric units (deg C) internally if supplied in English units.
	temp_regression_coefficients : tuple
		Four-element tuple of (intercept [deg C], flow coefficient [per
		cfs], air-temperature coefficient [per deg C], RMS error [deg C]).
		Only the first three elements are used in the calculation; RMS
		error is informational only and not applied here.
	currentAlternative : object, optional
		HEC-ResSim alternative object used for logging compute messages, if
		provided.

	Returns
	-------
	TimeSeriesMath
		Hourly estimated water-temperature time series, in degrees C,
		spanning the air-temperature series' valid date range.

	Notes
	-----
	Per the original developer's notes: flow and air temperature are each
	smoothed with a 7-day centered moving average before the regression is
	applied; flow is expected in CFS and air temperature in degrees C, and
	the resulting water temperature is in degrees C. Air temperature is
	first transformed to a daily average, then re-expressed in Celsius
	regardless of its original unit label (the "F"/"C" substring checks
	below assume the unit string's letter case and content follow this
	convention). The final regression result, computed on a daily basis
	internally, is interpolated ("INT") onto an hourly output grid.
	"""
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
	# Apply the flow term using a 7-day centered moving average of flow.
	tsmath_watertemp = tsmath_flow.centeredMovingAverage(7, False, True).multiply(temp_regression_coefficients[1])
	tsmath_watertemp.setUnits("deg C")
	if DEBUG: print "\tApplying air temperature..."
	# Add the air-temperature term using a 7-day centered moving average of
	# air temperature.
	tsmath_watertemp = tsmath_watertemp.add(tsmath_airtemp.centeredMovingAverage(7, False, True).multiply(temp_regression_coefficients[2]))
	if DEBUG: print "\tApplying constant..."
	tsmath_watertemp = tsmath_watertemp.add(temp_regression_coefficients[0])
	start_time = HecTime(tsmath_airtemp.firstValidDate(), HecTime.MINUTE_INCREMENT)
	start_time.setTime("0000")
	end_time = HecTime(tsmath_airtemp.lastValidDate(), HecTime.MINUTE_INCREMENT)
	# print "Starts at " + start_time.dateAndTime(4)
	# print "Ends at " + end_time.dateAndTime(4)
	# Interpolate the daily regression result onto an hourly output grid.
	tsmath_out = tsmath.generateRegularIntervalTimeSeries(start_time.dateAndTime(4), end_time.dateAndTime(4), "1HOUR", "", 0.0)
	tsmath_out.setUnits("deg C")
	tsmath_out = tsmath_watertemp.transformTimeSeries(tsmath_out, "INT")
	tsmath_out.setParameterPart("TEMP-WATER")

	return tsmath_out

def leapYearTest(currentAlternative):
	"""Log HecTime values around a leap-year boundary for diagnostic purposes.

	Parameters
	----------
	currentAlternative : object
		HEC-ResSim alternative object used to log the computed HecTime
		minute values via ``addComputeMessage``.

	Returns
	-------
	None

	Notes
	-----
	Uses year 3000 as a leap-year test case (verifying HecTime.isLeap
	treats it as a leap year per the Gregorian calendar's 400-year rule)
	by logging the internal minute values for 28 Feb, 29 Feb, and 1 Mar of
	that year. Purely diagnostic; does not return or assert anything.
	"""
	test = HecTime(HecTime.MINUTE_INCREMENT)
	test.setYearMonthDay(3000, 2, 28, 1440)
	currentAlternative.addComputeMessage("HecTime 28 Feb 3000 = %d"%(test.getMinutes()))
	test.setYearMonthDay(3000, 2, 29, 1440)
	currentAlternative.addComputeMessage("HecTime 29 Feb 3000 = %d"%(test.getMinutes()))
	test.setYearMonthDay(3000, 3, 1, 1440)
	currentAlternative.addComputeMessage("HecTime 1 Mar 3000 = %d"%(test.getMinutes()))
	return