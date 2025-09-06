//Utility (Javascript core functionality extension)
const dateExpression = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;
const monthsShort = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const monthsLong = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const weeksShort = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const weeksLong = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const regexMonthsShort = 'Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec';
const regexMonthsLong = 'January|February|March|April|May|June|July|August|September|October|November|December';
const regexWeeksLong = 'Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday';
const regexWeeksShort = 'Sun|Mon|Tue|Wed|Thu|Fri|Sat';
class _utility {
    String = {
        /**
         * Strips last character from string
         */
        strip(val, count = 1) {
            return val.substr(0, val.length - count);
        },
        insertAt(value, index, expr) {
            if (index > value.length)
                index = value.length;
            var leftPart = value.substr(0, index);
            var rightPart = value.substr(index);
            var retval = leftPart + expr + rightPart;
            return retval;
        },
        /**
         * Splits string on specific
         */
        split(value, separator, removeEmpty = false) {
            let e = value.replace(new RegExp(`${separator}{2}`, 'g'), '\x07'); //Replace double separator instances with special character
            let retval = e.split(separator); //split on the basis of separator
            for (let i = 0; i < retval.length; i++) //Substitute special character with single separator instance
                retval[i] = retval[i].replace(/\x07/g, separator);
            if (removeEmpty) //Remove empty splits (if asked for)
                for (let i = retval.length - 1; i >= 0; i--)
                    if (!retval[i])
                        retval.splice(i, 1);
            return retval;
        },
        escapeHTML(unsafe) {
            return unsafe
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&apos;");
        }
    };
    Number = {
        format(value, mask) {
            function formatNumber(mask, value) {
                let retval = ''; //Return value
                let i, j;
                let indexDecimalPoint = mask.indexOf('.'); //dot position (if any)
                let mskInteger = indexDecimalPoint === -1 ? mask : mask.substr(0, indexDecimalPoint); //Extract integer part of mask
                let mskFraction = indexDecimalPoint === -1 ? '' : mask.substr(indexDecimalPoint + 1, mask.length - indexDecimalPoint); //Extract fraction part of mask
                let flgZero = false, flgHash = false, flgComma = false, flgDecimal = false;
                for (i = 0; i < mskInteger.length; i++) { //Validate mask
                    let c = mskInteger.charAt(i);
                    if (c === '.') { //decimal
                        if (flgDecimal)
                            return ''; //There cannot be two decimal places
                        if (flgComma)
                            return ''; //Comma cannot preceed decimal
                        flgDecimal = true; //flag that decimal point has been detected
                    }
                    else if (c === ',') { //comma
                        if (flgComma)
                            return ''; //There cannot be two consecutive commas
                        if (flgDecimal)
                            return ''; //Fraction portion cannot contain comma
                        flgComma = true;
                    }
                    else if (c === '#') { //hash
                        if (flgDecimal)
                            return ''; //Fraction portion cannot have hash
                        if (flgZero)
                            return ''; //Hash cannot appear after Zeros
                        flgHash = true; //flag that has has been detected
                        flgComma = false; //reset comma detection
                    }
                    else { //zero
                        flgZero = true; //flag that zero has been detected
                        flgComma = true; //reset comma detection
                    }
                }
                let numSign = Math.sign(value);
                let val = Math.abs(value); //Remove number sign for formatting
                let numInteger = Math.trunc(val); //Extract integer portion of number
                let numFraction = val - numInteger; //Extract fraction portion of number
                let numIntegerFixedCount = mskInteger.replace(/[#,]+/g, '').length; //number of fixed digits to show on integer part
                let numIntegerTotalCount = mskInteger.replace(/[,]+/g, '').length; //total number of formatted digits to show on integer part
                let numIntegerDigitCount = Math.floor(Math.log10(numInteger)) + 1; //total number of unformatted digits to show on integer part
                if (!Number.isFinite(numIntegerDigitCount))
                    numIntegerDigitCount = 1; //Zero to be handled as single digit
                retval = numInteger.toString(); //First convert integer part to string
                if (numIntegerDigitCount > numIntegerTotalCount) //Pad extra has to the left (if mask falls short)
                    mskInteger = '#'.repeat(numIntegerDigitCount - numIntegerTotalCount) + mskInteger;
                if (numIntegerDigitCount < numIntegerTotalCount) //Pad extra zeros to the left (if required)
                    retval = '0'.repeat(numIntegerTotalCount - numIntegerDigitCount) + retval;
                //Format integer part with comma mask
                for (i = 0; i < mskInteger.length; i++)
                    if (mskInteger.charAt(i) === ',')
                        retval = utility.String.insertAt(retval, i, ',');
                //Remove extra zeros from left as per mask
                let stripCount = 0;
                for (i = 0; i < mskInteger.length; i++) {
                    let cInteger = retval.charCodeAt(i); //ASCII value of number index
                    let chMask = mskInteger[i]; //Character at mask index
                    if (chMask === '0' || (chMask === '#' && cInteger > 48))
                        break;
                    else
                        stripCount++;
                }
                retval = retval.substr(stripCount, retval.length - stripCount);
                if (mskFraction.length)
                    retval += '.' + numFraction.toFixed(mskFraction.length).substr(2);
                return retval;
            }
            ;
            let sign = Math.sign(value);
            value = Math.abs(value);
            if (mask.includes(';')) { //Handle positive-negative-neutral
                let parts = mask.split(';');
                if (sign == 1)
                    mask = parts[0];
                else if (sign == -1)
                    mask = parts[1];
                else
                    mask = parts.length == 3 ? parts[2] : parts[0];
            }
            //Extract prefix-suffix-mask
            let prefix = '', suffix = '';
            let maskParts = /([#,0\.]+)/g.exec(mask);
            if (maskParts) {
                prefix = mask.substr(0, maskParts.index) || '';
                suffix = mask.substr(maskParts.index + maskParts[1].length) || '';
                mask = maskParts[1];
            }
            let replacedValue = formatNumber(mask, value);
            let retval = prefix + replacedValue + suffix;
            return retval;
        },
        round(value, precision = 0) {
            if (!value)
                return 0;
            let _value = value * Math.pow(10, precision);
            if (_value - Math.trunc(_value) > 0.5)
                _value = Math.trunc(_value) + 1;
            else
                _value = Math.trunc(_value);
            return _value / Math.pow(10, precision);
        }
    };
    Date = {
        /**
         * Returns today's date without time value
         */
        today() {
            let today = new Date(); //Calculate milliseconds elapsed till this moment
            return new Date(today.getFullYear(), today.getMonth(), today.getDate(), 0, 0, 0, 0);
        },
        /**
         * Calculates date with desired difference (in milli-senconds)
         * @param dt Target date to add/subtract difference
         * @param ms Milli-seconds to add/substract
         */
        diff(dt, ms) {
            let retval = dt.valueOf(); //Calculate milliseconds elapsed till this moment
            retval += ms; //Add(-Subtract) milliseconds
            return new Date(retval);
        },
        dateReviver(key, value) {
            if (typeof value === 'string' && dateExpression.test(value))
                return new Date(value);
            return value;
        },
        format(value, mask) {
            let vDay = value.getDate();
            let vMonth = value.getMonth();
            let vYear = value.getFullYear();
            let vWeek = value.getDay();
            let vHour = value.getHours();
            let vMinute = value.getMinutes();
            let vSecond = value.getSeconds();
            //Year replacement
            if (/yyyy/.test(mask))
                mask = mask.replace('yyyy', vYear.toString());
            else if (/yy/.test(mask))
                mask = mask.replace('yy', vYear.toString().substr(2, 3));
            else
                ;
            //Month replacement
            if (/MMMM/.test(mask))
                mask = mask.replace('MMMM', monthsLong[vMonth]);
            else if (/MMM/.test(mask))
                mask = mask.replace('MMM', monthsShort[vMonth]);
            else if (/MM/.test(mask))
                mask = mask.replace('MM', (vMonth + 1).toString().padStart(2, '0'));
            else if (/M/.test(mask))
                mask = mask.replace('M', (vMonth + 1).toString());
            else
                ;
            //Day replacement
            if (/dddd/.test(mask))
                mask = mask.replace('dddd', weeksLong[vWeek]);
            else if (/ddd/.test(mask))
                mask = mask.replace('ddd', weeksShort[vWeek]);
            else if (/dd/.test(mask))
                mask = mask.replace('dd', vDay.toString().padStart(2, '0'));
            else if (/d/.test(mask))
                mask = mask.replace('d', vDay.toString());
            else
                ;
            //Hour replacement
            if (/HH/.test(mask))
                mask = mask.replace('HH', vHour.toString().padStart(2, '0'));
            else if (/H/.test(mask))
                mask = mask.replace('H', vHour.toString());
            else if (/hh/.test(mask))
                mask = mask.replace('hh', (vHour % 12 ? 0 : vHour % 12).toString().padStart(2, '0'));
            else if (/h/.test(mask))
                mask = mask.replace('h', (vHour % 12 ? 0 : vHour % 12).toString());
            else
                ;
            //Minute replacement
            if (/mm/.test(mask))
                mask = mask.replace('mm', vMinute.toString().padStart(2, '0'));
            else if (/m/.test(mask))
                mask = mask.replace('m', vMinute.toString());
            else
                ;
            //Second replacement
            if (/ss/.test(mask))
                mask = mask.replace('ss', vSecond.toString().padStart(2, '0'));
            else if (/s/.test(mask))
                mask = mask.replace('s', vSecond.toString());
            else
                ;
            //AM-PM replacement
            if (/tt/.test(mask))
                mask = mask.replace('tt', Math.floor(vHour / 12) ? 'PM' : 'AM');
            else
                ;
            return mask;
        },
        parse(value, format) {
            let vYear = 0, vMonth = 0, vDay = 0, vHour = 0, vMinute = 0, vSecond = 0;
            let parts = [];
            //Strip out format separators (if found)
            if (/[\:|\/|\.|\s|-]/.test(format)) { //Format separator found
                //Remove separator from values
                format = format.replace(/[\:|\/|\.|\s|-]/g, '');
                value = value.replace(/[\:|\/|\.|\s|-]/g, '');
            }
            //Extract date format parts
            parts = format.split(/(dddd|ddd|dd|d|MMMM|MMM|MM|M|yyyy|yy|HH|H|hh|h|mm|m|ss|s|tt|t)/g);
            for (let i = parts.length - 1; i >= 0; i--) //Remove empty parts
                if (!parts[i])
                    parts.splice(i, 1);
            //Construct regex expression to separate parts from value
            let regexValue = '^';
            for (let i = 0; i < parts.length; i++) {
                let capExpr = parts[i];
                if (capExpr == 'd')
                    capExpr = '[1-9]|[1-2][0-9]|3[0-1]';
                else if (capExpr == 'dd')
                    capExpr = '0[1-9]|[1-2][0-9]|3[0-1]';
                else if (capExpr == 'ddd')
                    capExpr = regexWeeksShort;
                else if (capExpr == 'dddd')
                    capExpr = regexWeeksLong;
                else if (capExpr == 'M')
                    capExpr = '1[0-2]|[1-9]';
                else if (capExpr == 'MM')
                    capExpr = '0[1-9]|1[0-2]';
                else if (capExpr == 'MMM')
                    capExpr = regexMonthsShort;
                else if (capExpr == 'MMMM')
                    capExpr = regexMonthsLong;
                else if (capExpr == 'yy')
                    capExpr = '\\d{2}';
                else if (capExpr == 'yyyy')
                    capExpr = '\\d{4}';
                else if (capExpr == 'H')
                    capExpr = '[1-9]|1[0-9]|2[0-3]';
                else if (capExpr == 'HH')
                    capExpr = '0[0-9]|1[0-9]|2[0-3]';
                else if (capExpr == 'h')
                    capExpr = '[1-9]|1[0-2]';
                else if (capExpr == 'hh')
                    capExpr = '0[1-9]|1[0-2]';
                else if (capExpr == 'm')
                    capExpr = '[1-9]|[1-5][0-9]';
                else if (capExpr == 'mm')
                    capExpr = '[0-5][0-9]';
                else if (capExpr == 's')
                    capExpr = '[1-9]|[1-5][0-9]';
                else if (capExpr == 'ss')
                    capExpr = '[0-5][0-9]';
                else if (capExpr == 'tt')
                    capExpr = 'a\\.?m\\.?|A\\.?M\\.?';
                else
                    ;
                regexValue += `(${capExpr})`;
            }
            regexValue += '$';
            let partResult = new RegExp(regexValue, 'g').exec(value);
            if (!partResult)
                return null;
            if (partResult.length !== parts.length + 1)
                return null; //Regex group match gives original value as extra (so ignored)
            for (let i = 0; i < parts.length; i++) {
                let partFormat = parts[i];
                let partValue = partResult[i + 1];
                let val = parseInt(partValue);
                if (partFormat == 'd' || partFormat == 'dd')
                    vDay = val;
                //else if (partFormat == 'ddd') vMonth = weeksShort.indexOf(partValue);
                //else if (partFormat == 'dddd') vMonth = weeksLong.indexOf(partValue);
                else if (partFormat == 'M' || partFormat == 'MM')
                    vMonth = --val;
                else if (partFormat == 'MMM')
                    vMonth = monthsShort.indexOf(partValue);
                else if (partFormat == 'MMMM')
                    vMonth = monthsLong.indexOf(partValue);
                else if (partFormat == 'yy' || partFormat == 'yyyy')
                    vYear = val;
                else if (partFormat == 'H' || partFormat == 'HH')
                    vHour = val;
                //else if (partFormat == 'h' || partFormat == 'hh') vHour = val; //am-pm handling to be impleamented
                else if (partFormat == 'm' || partFormat == 'mm')
                    vMinute = val;
                else if (partFormat == 's' || partFormat == 'ss')
                    vSecond = val;
                else
                    ;
            }
            //2 digit year handling
            if (vYear < 100)
                vYear += vYear > 71 ? 1900 : 2000; //upto 70 in 1900 centurary
            return new Date(vYear, vMonth, vDay, vHour, vMinute, vSecond);
        }
    };
    Object = {
        copyPropertyValues(source, target) {
            let lstProp = Object.getOwnPropertyNames(source);
            for (let i = 0; i < lstProp.length; i++)
                target[lstProp[i]] = source[lstProp[i]];
        }
    };
    Array = {
        distinct(source, field) {
            let retval = [];
            for (let i = 0; i < source.length; i++)
                if (!retval.includes(source[i][field]))
                    retval.push(source[i][field]);
            return retval;
        },
        unique(arr, prop) {
            let retval = [];
            for (let i = 0; i < arr.length; i++)
                if (retval.findIndex(p => p[prop] === arr[i][prop]) == -1)
                    retval.push(arr[i]);
            return retval;
        }
    };
}
let utility = new _utility(); //Create singleton instance of class
export { utility }; //Export singleton instance of class
//# sourceMappingURL=utility.mjs.map