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
    try:
        tout = dt.datetime.strptime(dtstr, '%Y-%m-%d, %H:%M')
    except ValueError as ve:
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
    if hecTime.hour() == 24:
        tout = dt.datetime(hecTime.year(), hecTime.month(), hecTime.day(), 23, hecTime.minute())
        tout += dt.timedelta(hours=1)
    else:
        tout = dt.datetime(hecTime.year(), hecTime.month(), hecTime.day(), hecTime.hour(), hecTime.minute())
    return tout


# Process hdf5 file to get cold water pool volume at the end of September
# And process DSS gate records to get dates of first side gate usage
def runIteration(modelAlternative, currentIteration, maxIteration):
    
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
    
    startIdx = idx * nz
    endIdx = (idx + 1) * nz
    print("Temperature profile", temps[startIdx:endIdx])
    tempOct1 = temps[startIdx:endIdx]
    volOct1 = vols[startIdx:endIdx]
    
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
            