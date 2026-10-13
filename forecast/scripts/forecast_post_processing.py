from ncsa.hdf.hdf5lib import H5, HDF5Constants
from jarray import zeros
from java.lang.reflect import Array
import java
import datetime as dt
import os
import time
from com.rma.model import Project
from hec.heclib.dss import HecDss

def str2datetime(dtstr):
    """Parse an HEC-style datetime string into a Python datetime.

    Parameters
    ----------
    dtstr : str
        Datetime string in "%Y-%m-%d, %H:%M" format, as produced by HEC
        HDF5 time-date-stamp datasets. May use hour "24" to represent
        midnight at the end of the given day (HEC convention) rather than
        the start of the next day.

    Returns
    -------
    datetime.datetime
        Parsed datetime. If the input hour field is "24", the string is
        patched to hour "23" for parsing and then advanced by one hour,
        yielding the correct midnight-of-next-day instant.

    Raises
    ------
    ValueError
        Re-raised if the input cannot be parsed even after accounting for
        the hour-24 convention.

    Notes
    -----
    This mirrors hecTime2datetime's hour-24 handling but operates on a raw
    string rather than an HecTime object, since HDF5 datetime datasets are
    stored as text.
    """
    try:
        tout = dt.datetime.strptime(dtstr, '%Y-%m-%d, %H:%M')
    except ValueError as ve:
        # HEC convention: hour "24" denotes midnight at the end of the
        # current day. Patch the hour field to "23" so strptime succeeds,
        # then add the missing hour to land on the correct instant.
        if dtstr[12:14] == '24':
            tmp_dtstr = list(dtstr.encode('ascii', 'ignore'))
            tmp_dtstr[13] = '3'
            tout = dt.datetime.strptime(''.join(tmp_dtstr), '%Y-%m-%d, %H:%M')
            tout += dt.timedelta(hours=1)
        else:
            print("Error converting datetime string: ", dtstr)
            raise ve
    return tout
    
def hecTime2datetime(hecTime):
    """Convert an HecTime object into a Python datetime.

    Parameters
    ----------
    hecTime : HecTime
        HEC time object to convert. May represent hour 24 (HEC convention
        for midnight at the end of the day) rather than hour 0 of the
        following day.

    Returns
    -------
    datetime.datetime
        Equivalent Python datetime. If ``hecTime.hour()`` is 24, the
        result is built using hour 23 and then advanced by one hour to
        land on the correct midnight-of-next-day instant.

    Notes
    -----
    Mirrors str2datetime's hour-24 handling but operates on an HecTime
    object rather than a formatted string.
    """
    if hecTime.hour() == 24:
        tout = dt.datetime(hecTime.year(), hecTime.month(), hecTime.day(), 23, hecTime.minute())
        tout += dt.timedelta(hours=1)
    else:
        tout = dt.datetime(hecTime.year(), hecTime.month(), hecTime.day(), hecTime.hour(), hecTime.minute())
    return tout


def runIteration(modelAlternative, currentIteration, maxIteration):
    """Post-process one HEC-WAT forecast iteration's water-quality and gate results.

    Reads the HEC water-quality HDF5 output to compute end-of-September
    cold-water-pool and total reservoir storage at Shasta Lake, reads DSS
    gate-operation time series to find the dates of first side-gate use and
    first exclusive side-gate use, and appends a summary row to a CSV
    report file.

    Parameters
    ----------
    modelAlternative : object
        HEC-WAT model alternative object describing the current run (name,
        simulation name, program, DSS filename, F-part, variant name, and
        run directory).
    currentIteration : int
        1-based index of the current forecast iteration. Iteration 1
        triggers creation of a new output CSV with a header row.
    maxIteration : int
        Total number of iterations in the run (unused directly in this
        function but accepted for interface consistency with other
        per-iteration post-processing scripts).

    Returns
    -------
    bool or str
        ``True`` on success. A string beginning with "Error:" is returned
        (not raised) if an HDF5 or DSS file/dataset could not be opened or
        read, allowing the caller to detect and report failures without an
        exception. A non-fatal "Warning:" string is assigned to a local
        variable and currently never returned (see Notes).

    Notes
    -----
    Script assumes English units for the watershed model (HDF5 volumes in
    ft^3, converted to acre-feet via /43560). The cold-water-pool and total
    storage are evaluated at the first HDF5 output time at or after 1
    October 00:00; if the simulation does not extend that far, values are
    reported for the last available time step and a warning message is
    built into ``rtnMsg``, but ``rtnMsg`` is never returned or surfaced
    (the function always returns ``True`` at the end on the success path)
    -- this appears to be a pre-existing gap between the warning logic and
    the return statement, preserved as-is. The "Lower gates" DSS read uses
    the same ``recordParts``/path string as the "Side gates" read
    immediately above it; this looks like a copy-paste omission (the C-part
    "GATE" is not changed to distinguish side vs. lower gates), but is
    preserved exactly rather than corrected.
    """
    
    scriptStartTime = time.time()
    
    print("Current iteration", currentIteration)
    print("Model Alternative", modelAlternative.getName())
    print("Simulation Name", modelAlternative.getSimulationName())
    print("Program", modelAlternative.getProgram())
    print("DSS Filename", modelAlternative.getDssFilename())
    print("Fpart", modelAlternative.getFpart())
    print("Variant Name", modelAlternative.getVariantName())
    print("Run directory", modelAlternative.getRunDirectory())
    
    simulationName = modelAlternative.getSimulationName().encode('ascii', 'ignore')
    rssRunName = modelAlternative.getFpart().encode('ascii', 'ignore')
    
    workspace = Project.getCurrentProject().getWorkspacePath()
    print(workspace)
    simDrct = os.path.join(workspace, "runs", simulationName)
    hdfFilename = rssRunName.replace(":", "_") + ".h5"
    FpartBaseName = rssRunName.upper()
    
    dssFilename = "iterationResults.dss"
    coldWaterPoolCutoffF = 56.  # in deg F
    outputFilename = 'SRTTG_reporting.csv'
    
    # Script assumes English units for watershed (ft3 volume output)
    
    # On the first iteration of a run, (re)create the CSV report with a
    # fresh header; subsequent iterations append to the existing file.
    if currentIteration == 1:
        # Create new file
        with open(os.path.join(simDrct, outputFilename), 'w') as outFid:
            outFid.write('Iteration,EOS CWP Stor (ac-ft),EOS Total Pool Stor (ac-ft),Date First Side Gate Use,Date First Exclusive Side Gate Use\n')

    # Open hdf file
    hdfFilenameFull = os.path.join(simDrct, 'rss', hdfFilename)
    fid = H5.H5Fopen(hdfFilenameFull, HDF5Constants.H5F_ACC_RDONLY, HDF5Constants.H5P_DEFAULT)
    if fid < 0:
        return ("Error: Unable to open Water Quality Output file: " + hdfFilenameFull)
    print("File id", fid)
    
    # Open time dataset
    path = "/Results/Subdomains/Time"
    try:
        dsId = H5.H5Dopen(fid, path, HDF5Constants.H5P_DEFAULT)
    except Exception as e:
        H5.H5Fclose(fid)
        return ("Error: Unable to open dataset at path: " + path + ", File: " + hdfFilenameFull)
    print("Dataset id", dsId)
    # Get dimensions
    spaceId = H5.H5Dget_space(dsId)
    print("Dataspace id", spaceId)
    dsDims1 = zeros(1, 'l')
    maxDims1 = zeros(1, 'l')
    H5.H5Sget_simple_extent_dims(spaceId, dsDims1, maxDims1)
    nt = dsDims1[0]
    print("Number of output times", nt)
    times = zeros(nt, 'd')
    # Read data
    try:
        readError = H5.H5Dread_double(dsId, HDF5Constants.H5T_NATIVE_DOUBLE, HDF5Constants.H5S_ALL, HDF5Constants.H5S_ALL, HDF5Constants.H5P_DEFAULT, times)
    except Exception as e:
        H5.H5Sclose(spaceId)
        H5.H5Dclose(dsId)
        H5.H5Fclose(fid)
        return ("Error: Unable to read dataset at path: " + path + ", File: " + hdfFilenameFull)
    print("First time", times[0])
    H5.H5Sclose(spaceId)
    H5.H5Dclose(dsId)
    
    # Derive the model's output time step (hours) from the first two time
    # values, which are stored in HDF5 as fractional days.
    delta_t_hrs = int(round((times[1] - times[0]) * 24., 0))
    delta_t = dt.timedelta(hours=delta_t_hrs)
    
    # Open and read the datetime dataset
    path = "/Results/Subdomains/Time Date Stamp"
    dsId = H5.H5Dopen(fid, path, HDF5Constants.H5P_DEFAULT)
    print("Dataset id", dsId)
    typeId = H5.H5Dget_type(dsId)
    print("Type id", typeId)
    typeSize = H5.H5Tget_size(typeId)
    spaceId = H5.H5Dget_space(dsId)
    print("Space id", spaceId)
    H5.H5Sget_simple_extent_dims(spaceId, dsDims1, maxDims1)
    
    # Fixed-length Fortran-style string dataset: build a matching in-memory
    # string type before reading, since HDF5 string datasets require an
    # explicit memory datatype of the correct fixed size.
    memoryType = H5.H5Tcopy(HDF5Constants.H5T_FORTRAN_S1)
    H5.H5Tset_size(memoryType, typeSize)
    memspaceId = H5.H5Screate_simple(1, dsDims1, maxDims1)
    print("Memory Space id", memspaceId)
    strings = Array.newInstance(java.lang.String, dsDims1[0])
    H5.H5Dread_string(dsId, memoryType, memspaceId, spaceId, HDF5Constants.H5P_DEFAULT, strings)
    H5.H5Sclose(memspaceId)
    H5.H5Sclose(spaceId)
    H5.H5Tclose(typeId)
    H5.H5Dclose(dsId)
    
    startTime = str2datetime(strings[0])
    print(startTime)
    endTime = str2datetime(strings[-1])
    print(endTime)
    
    # Find Oct 1 00:00 index
    oct1 = dt.datetime(startTime.year, 10, 1)
    idx = int(round((oct1 - startTime).total_seconds() / delta_t.total_seconds()))
    rtnMsg = ""
    # Clamp to the last available output time if the simulation ends before
    # 1 October; only warn once, on the first iteration, to avoid repeating
    # the same warning across every iteration of a multi-iteration run.
    if idx > nt-1:
        idx = nt-1
        if currentIteration == 1:
            rtnMsg = ("Warning: Simulation does not go until the end of September." + "\n" +
                      "Storages will be reported for the last model time step.")
    tstr = strings[idx]
    print("Oct 1", tstr)
    print("idx", idx)
    
    # Read temperature record for Shasta
    path = "/Results/Subdomains/Shasta Lake/Water Temperature"
    try:
        dsId = H5.H5Dopen(fid, path, HDF5Constants.H5P_DEFAULT)
    except Exception as e:
        H5.H5Fclose(fid)
        return ("Error: Unable to open dataset at path: " + path + ", File: " + hdfFilenameFull)
    print("Dataset id", dsId)
    # Get dimensions
    spaceId = H5.H5Dget_space(dsId)
    print("Dataspace id", spaceId)
    dsDims2 = zeros(2, 'l')
    maxDims2 = zeros(2, 'l')
    H5.H5Sget_simple_extent_dims(spaceId, dsDims2, maxDims2)
    nz = dsDims2[1]
    print("Number of vertical layers", nz)
    nvals = nt * nz
    temps = zeros(nvals, 'd')
    # Read data
    try:
        readError = H5.H5Dread_double(dsId, HDF5Constants.H5T_NATIVE_DOUBLE, HDF5Constants.H5S_ALL, HDF5Constants.H5S_ALL, HDF5Constants.H5P_DEFAULT, temps)
    except Exception as e:
        H5.H5Sclose(spaceId)
        H5.H5Dclose(dsId)
        H5.H5Fclose(fid)
        return ("Error: Unable to read dataset at path: " + path + ", File: " + hdfFilenameFull)
    H5.H5Sclose(spaceId)
    H5.H5Dclose(dsId)
    
    # Read volume record for Shasta
    path = "/Results/Subdomains/Shasta Lake/Cell volume"
    try:
        dsId = H5.H5Dopen(fid, path, HDF5Constants.H5P_DEFAULT)
    except Exception as e:
        H5.H5Fclose(fid)
        return ("Error: Unable to open dataset at path: " + path + ", File: " + hdfFilenameFull)
    print("Dataset id", dsId)
    # Assume same dimensions as temperature
    vols = zeros(nvals, 'd')
    # Read data
    try:
        readError = H5.H5Dread_double(dsId, HDF5Constants.H5T_NATIVE_DOUBLE, HDF5Constants.H5S_ALL, HDF5Constants.H5S_ALL, HDF5Constants.H5P_DEFAULT, vols)
    except Exception as e:
        H5.H5Dclose(dsId)
        H5.H5Fclose(fid)
        return ("Error: Unable to read dataset at path: " + path + ", File: " + hdfFilenameFull)
    H5.H5Dclose(dsId)
    
    # Close file
    H5.H5Fclose(fid)
    
    # Temperature/volume arrays are flattened across (time, layer); slice
    # out the vertical profile for the single target time step found above.
    startIdx = idx * nz
    endIdx = (idx + 1) * nz
    print("Temperature profile", temps[startIdx:endIdx])
    tempOct1 = temps[startIdx:endIdx]
    volOct1 = vols[startIdx:endIdx]
    
    # Sum layer volumes below the cold-water-pool temperature cutoff (56 F,
    # converted to Celsius here since HDF5 temperatures are in deg C) to get
    # cold-water-pool volume, alongside the total pool volume across all
    # layers; both are converted from ft^3 to acre-feet (1 ac-ft = 43,560 ft^3).
    coldWaterPoolCutoffC = (coldWaterPoolCutoffF - 32.) * 5. / 9.
    cwp = 0.
    poolVol = 0.
    for j in range(nz):
        poolVol += volOct1[j]
        if tempOct1[j] < coldWaterPoolCutoffC:
            cwp += volOct1[j]
    cwp = cwp / 43560.  # convert to ac-ft
    poolVol = poolVol / 43560.
    print("Cold Water Pool (ac-ft)", cwp)
    print("Total Pool Stor (ac-ft)", poolVol)
    
    # DSS file processing
    try:
        dssFile = HecDss.open(os.path.join(simDrct, dssFilename))
    except Exception as e:
        return ("Error: Unable to open DSS file: " + dssFilename)
    collectionId = "{0:0>6d}".format(currentIteration)
    Fpart = "C:" + collectionId + "|" + FpartBaseName
    # Side gates
    # TODO: script the 1HOUR part of this
    recordParts = ["", "", "TOTAL_TCDL_GATES_FORECAST", "GATE", "*", "1HOUR", Fpart, ""]
    recordName = "/".join(recordParts)
    try:
        dssTSMathSide = dssFile.read(recordName)
    except Exception as e:
        return ("Error: Unable to read DSS path: " + recordName + ", File: " + dssFilename)
        
    tsContainerSide = dssTSMathSide.getContainer()
    # Lower gates
    recordParts = ["", "", "TOTAL_TCDL_GATES_FORECAST", "GATE", "*", "1HOUR", Fpart, ""]
    recordName = "/".join(recordParts)
    try:
        dssTSMathLower = dssFile.read(recordName)
    except Exception as e:
        return ("Error: Unable to read DSS path: " + recordName + ", File: " + dssFilename)
    tsContainerLower = dssTSMathLower.getContainer()
    
    # Find May 1 00:00 index
    dssStartTime = hecTime2datetime(tsContainerSide.getStartTime())
    may1 = dt.datetime(dssStartTime.year, 5, 1)
    mayIdx = int(round((may1 - dssStartTime).total_seconds() / delta_t.total_seconds()))
    mayIdx = max(mayIdx, 0)  # in case simulation is starting after May 1
    n = tsContainerSide.getNumberValues()
    if mayIdx > n-1:  # if simulation doesn't go past May 1, start at first day of simulation
        mayIdx = 0
    
    # Scan forward from May 1 to find the first time step with any side-gate
    # opening, and separately the first time step where a side gate is open
    # while the lower gate is fully closed (an "exclusive" side-gate use).
    foundFirst = False
    foundExclusive = False
    idxFirst = -1
    idxExclusive = -1
    for j in range(mayIdx, n):
        if tsContainerSide.getValue(j) > 0 and not foundFirst:
            foundFirst = True
            idxFirst = j
        if tsContainerSide.getValue(j) > 0 and tsContainerLower.getValue(j) == 0:
            foundExclusive = True
            idxExclusive = j
            break
    if foundFirst:
        dateFirst = (tsContainerSide.getHecTime(idxFirst)).toString().replace(',','')
    else:
        dateFirst = "***"
    if foundExclusive:
        dateExclusive = (tsContainerSide.getHecTime(idxExclusive)).toString().replace(',','')
    else:
        dateExclusive = "***"
  
    print("First side gate usage", dateFirst)
    print("First exclusive side gate usage", dateExclusive)
    
    # Append results to csv file
    with open(os.path.join(simDrct, outputFilename), 'a') as outFid:
        outFid.write("{0:d},{1:0.2f},{2:0.2f},{3:s},{4:s}\n".format(currentIteration, cwp, poolVol, dateFirst, dateExclusive))
    
    scriptEndTime = time.time()
    elapsedTime = scriptEndTime - scriptStartTime
    print("Elapsed time", elapsedTime)
    
    #raise ValueError
    #return rtnMsg
    return True