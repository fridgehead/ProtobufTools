import sys
import traceback
import struct
import argparse


creationCount = 0

class DataTypes:
    VarInt, Bit64, LenDelim, StartGroup, EndGroup, Bit32, Empty = range(7)

'''
    A protobuf field
'''
class Field:
    def __init__ (self):
        global creationCount
        self.position = 0 # position of the data in the stream
        self.datatype = DataTypes.Empty # data type
        self.value = None
        self.fieldid = 0
        creationCount+=1

    def addChild(self, child):
        if type(self.value) != list:
            self.value = []
        self.value.append(child)



'''
    Decode a varInt and move cursor
'''
def readVarInt(buffer, pos):
  mask = (1 << 64) - 1
  result = 0
  shift = 0
  startPos = pos
  while 1:
    b = ord(buffer[pos])
    result |= ((b & 0x7f) << shift)
    pos += 1
    if not (b & 0x80):
      if result > 0x7fffffffffffffff:
        result -= (1 << 64)
        result |= ~mask
      else:
        result &= mask
      retObj = Field()
      retObj.datatype = DataTypes.VarInt
      retObj.value = result
      return (result, pos, pos-startPos, retObj)
    shift += 7
    if shift >= 64:
      raise Error('Too many bytes when decoding varint.')

'''
Read 8 bytes
'''
def readQWORD(d, pos):
    retObj = Field()
    try:
        v = struct.unpack("<Q", d[pos:pos+8])[0]
        v = d[pos:pos+8]
        retObj.position = pos - 2
        retObj.value = struct.unpack('d', v)[0]
        retObj.datatype = DataTypes.Bit64
    except:
        print "Exception in readQWORD"
        print sys.exc_info()
        return (None, pos, retObj)
    pos += 8
    return (v, pos, retObj);

def readDWORD(d, pos):
    retObj = Field()
    try:
        v = struct.unpack("<L", d[pos:pos+4])[0]
        retObj.value = v
        retObj.datatype = DataTypes.Bit32
    except:
        print "Exception in readDWORD"
        print sys.exc_info()
        return (None, pos)
    pos += 4
    return (v, pos, retObj);

def readBYTE(d, pos):
    try:
        v = struct.unpack("<B", d[pos:pos+1])[0]
    except:
        print "Exception in readBYTE"
        print sys.exc_info()
        return (None, pos)
    pos += 1
    return (v, pos);

'''
    read a field
    returns value, cursor pos after read, the data type, field id and value length
'''
def readField(d, pos):
    # read field and type info
    objpos = pos
    (v, p) = readBYTE(d, pos);
    datatype = v & 7;
    fieldnum = v >> 3;
    print "ReadField - datatype : %i " % datatype

    if datatype == 0:       # varint
        (v, p, l, obj) = readVarInt(d, p)
        obj.datatype = DataTypes.VarInt
        obj.fieldid = fieldnum
        obj.position = objpos
        return (v, p, datatype, fieldnum, l, obj)    
    elif datatype == 1: # 64-bit
        (v,p, obj) = readQWORD(d, p)
        obj.datatype = datatype
        obj.fieldid = fieldnum
        obj.position = objpos
        return (v, p, datatype, fieldnum, 8, obj)    
    elif datatype == 2: # varlen string/blob
        (fieldLen, p, l, obj) = readVarInt(d, p)    # get string length
        # try to determine if this is a string or an embedded message
        # attempt to read the values as an object and see what happens
        obj.fieldid = fieldnum
        obj.datatype = DataTypes.LenDelim
        obj.position = objpos
        subData = d[p:p+fieldLen]
        print "var length, looks like this: %s" % (subData.encode("string-escape"))

        # take a guess to see if this is a string or not
        # read the next two bytes, an embedded message should decode into
        # sensible values.
        (testval, _) = readBYTE(subData, 0);
        testdatatype = testval & 7;
        testfieldnum = testval >> 3;
        (testlen, _, _, _) = readVarInt(subData,1)
        testlen += 1
        print "lengthD: %i lengthSub: %i" % (testlen , len(subData))
        print "if its an object its field is: %i datat:%i" % (testfieldnum, testdatatype)
        processAsObject = False
        if testlen < fieldLen:
            print "most likely a sub object"
            # this is the only case we're interested in
            # automatically parse this as an object
            processAsObject = True
        else :
            if testdatatype == 2:
                print "probably a string"
            elif testdatatype == 1:
                print "most likely a long"
                processAsObject = True
            elif testdatatype == 0:
                print "most likely a varint"
                processAsObject = True
            elif testdatatype == 5:
                print "most likely a 32bit"
                processAsObject = True

            else:
                print "Most likely a string"

        if processAsObject == True:
            # this needs to be done multiple times
            startpos = 0
            # skim over sub object data and attempt to read fields until data runs out
            # TODO:
            # make this pass enture data stream with start+len rather than sub-sections of the data
            # its fucking the char pos stuff up atm
            while startpos < fieldLen: 
                (subValue, postReadPos, subDataType, subFieldNum, subLength, subObj) = readField(d, p+startpos)
                obj.addChild(subObj)
                subObj.position = p + startpos
                startpos = postReadPos - p

            # return data gathered about *this* object, no the subs
            retval =  (subData, p+fieldLen, datatype, fieldnum, fieldLen, obj)       

        else:
            obj.value = subData
            obj.position = p 
            retval =  (subData, p+fieldLen, datatype, fieldnum, fieldLen, obj)       
        print "----------------------"
        return retval
    elif datatype == 5: # 32-bit value
        (v,p, obj) = readDWORD(d, p)
        obj.fieldid = fieldnum
        obj.position = objpos
        return (v, p, datatype, fieldnum, 4, obj)
    else:
        print "Unknown type: %d [%x]\n" % (datatype, pos)
        return (None, p, datatype, fieldnum, 1);

# check data to see if it is a valid sub object or a string
# calls readfield and bails on error 
def isString(d):
    try :
        readField(d, 0) 
        print "is string managed to read as field" 
        
        return 0 
    except:
        print "exception when testing field - probably a string"
        print traceback.print_exc()
        return 1

def logOutput(string, filestream = None):
    print string
    if filestream is not None:
        filestream.write (string + "\r\n")

def PrintObject(obj, level=0, filestream = None):
    level += 1
    s = " " * level 
    if type(obj) == list: 
        logOutput( s + "{", filestream)
        for o in obj:
            PrintObject(o, level+2, filestream)
        logOutput( s + "}", filestream)
        return
    elif type(obj.value) == list:
        #print s + "%i object @%i {" % (obj.fieldid, obj.position)
        logOutput(s + "'" + str(obj.fieldid) + "' : {", filestream)
        for o in obj.value:
            PrintObject(o, level+2, filestream)
        logOutput (s + "}")
        return
     
    # primitives
    outStr = s   
    if type(obj.value) == str:
        
        print s + "%i string @%i: %s" % (obj.fieldid, obj.position, obj.value)
        logOutput(s + "'" + str(obj.fieldid) + "' : '" + obj.value + "'", filestream)
    elif type (obj.value) == int:
        print s + "%i int: @%i: %i" % (obj.fieldid, obj.position, obj.value)
        logOutput(s + "'" + str(obj.fieldid) + "' : " + str(obj.value), filestream )
    elif type (obj.value) == float:
        print s + "%i float @%i: %.10f" % (obj.fieldid, obj.position, obj.value)
        logOutput(s + "'" + str(obj.fieldid) + "' : " + str(obj.value), filestream )
    elif type (obj.value) == long:
        print s + "%i long @%i: %i" % (obj.fieldid, obj.position, obj.value)
        logOutput(s + "'" + str(obj.fieldid) + "' : " + str(obj.value), filestream)
    else:
        print type(obj.value)

    

# print an object to some sort of json-like format
def PrintObjects(obj, jsonFile=None):

    if jsonFile is not None:
        f = open (jsonFile, "w")
         
        PrintObject(obj, filestream=f)
        f.close()
    else:
        PrintObject(obj)

        
    pass

outputObject = []
def ParseString (instring, startpos=0):
    print "data len: %i" % (len(instring))
    pos = startpos
    while pos < len(instring):
        (d, p, t, fid, l, obj)  = readField(instring,pos);
        pos = p
        outputObject.append(obj)

# main
if __name__ == "__main__":
   
    parser = argparse.ArgumentParser(description="dump them buffs eh")
    group = parser.add_mutually_exclusive_group(required=True)

    group.add_argument("--str", help="the string to decode", dest="inString")
    group.add_argument("--raw", help="the string is raw, rather than bytes", dest="rawString")
    group.add_argument("--file", help="file to load", dest="fileName")

    parser.add_argument("--outjson", help="dump data to json", dest="jsonOut", nargs="?")

    


    args = parser.parse_args()
    # been given as hex byte string
    if args.inString != None: 
        print "parsing byte string"
        instring = args.inString.replace(" ","")
        splitString = [instring[i:i+2] for i in range(0, len(instring), 2)]
        finalString = "".join([chr(int(b, 16)) for b in splitString])

        ParseString(finalString)
    elif args.rawString != None:
        print "parsing raw string: " + args.rawString
        ParseString(args.rawString)
    elif args.fileName != None:
        print "loading file.."
        f = open (args.fileName, "rb")
        data = f.read()
        f.close()
         
        ParseString(data)

    PrintObjects(outputObject, jsonFile=args.jsonOut)
