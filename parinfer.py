## Parinfer.py - a Parinfer implementation in Python
## v0.7.0
## https://github.com/oakmac/parinfer.py
##
## More information about Parinfer can be found here:
## http://shaunlebron.github.io/parinfer/
##
## Copyright (c) 2015, Chris Oakman and other contributors
## Released under the ISC license
## https://github.com/oakmac/parinfer.py/blob/master/LICENSE.md

import re

# -------------------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------------------

INDENT_MODE = 'INDENT_MODE'
PAREN_MODE = 'PAREN_MODE'

BACKSLASH = '\\'
BLANK_SPACE = ' '
DOUBLE_SPACE = '  '
DOUBLE_QUOTE = '"'
NEWLINE = '\n'
SEMICOLON = ';'
TAB = '\t'

LINE_ENDING_REGEX = re.compile(r"\r?\n")

CLOSE_PARENS = frozenset(['}', ')', ']'])

PARENS = {
    '{': '}',
    '}': '{',
    '[': ']',
    ']': '[',
    '(': ')',
    ')': '(',
}


# -------------------------------------------------------------------------------
# String Operations
# -------------------------------------------------------------------------------

def insertWithinString(orig, idx, insert):
    return orig[:idx] + insert + orig[idx:]


def replaceWithinString(orig, start, end, replace):
    return orig[:start] + replace + orig[end:]


def removeWithinString(orig, start, end):
    return orig[:start] + orig[end:]


def repeatString(text, n):
    return text * n


# NOTE: We assume that if the CR char "\r" is used anywhere, we should use CRLF
#       line-endings after every line.
def getLineEnding(text):
    return "\r\n" if "\r" in text else "\n"


# -------------------------------------------------------------------------------
# Possible Errors
# -------------------------------------------------------------------------------

ERROR_QUOTE_DANGER = "quote-danger"
ERROR_EOL_BACKSLASH = "eol-backslash"
ERROR_UNCLOSED_QUOTE = "unclosed-quote"
ERROR_UNCLOSED_PAREN = "unclosed-paren"
ERROR_UNHANDLED = "unhandled"

errorMessages = {
    ERROR_QUOTE_DANGER: "Quotes must balanced inside comment blocks.",
    ERROR_EOL_BACKSLASH: "Line cannot end in a hanging backslash.",
    ERROR_UNCLOSED_QUOTE: "String is missing a closing quote.",
    ERROR_UNCLOSED_PAREN: "Unmatched open-paren.",
}


class ParinferError(Exception):
    pass


# -------------------------------------------------------------------------------
# Misc Utils
# -------------------------------------------------------------------------------

def clamp(valN, minN, maxN):
    if minN is not None:
        valN = max(minN, valN)
    if maxN is not None:
        valN = min(maxN, valN)
    return valN


def peek(arr):
    return arr[-1] if arr else None


# -------------------------------------------------------------------------------
# Character Functions
# -------------------------------------------------------------------------------

def isValidCloseParen(parenStack, ch):
    if len(parenStack) == 0:
        return False
    return peek(parenStack)['ch'] == PARENS[ch]


def processText(text, options, mode):
    result = Result(text, options, mode)

    try:
        for line in result.origLines:
            result.processLine(line)
        result.finalizeResult()
    except ParinferError as e:
        errorDetails = e.args[0]
        result.processError(errorDetails)

    return result


class Result(object):
    # -------------------------------------------------------------------------------
    # Result Structure
    # -------------------------------------------------------------------------------
    def __init__(self, text, options, mode):
        vars(self).update(dict(
            mode=mode,
            origText=text,
            origLines=text.split(NEWLINE),
            lines=[],
            lineNo=-1,
            ch='',
            x=0,
            parenStack=[],
            parenTrail=dict(
                lineNo=None,
                startX=None,
                endX=None,
                openers=[],
            ),
            cursorX=None,
            cursorLine=None,
            cursorDx=None,
            isInCode=True,
            isEscaping=False,
            isInStr=False,
            isInComment=False,
            commentX=None,
            quoteDanger=False,
            trackingIndent=False,
            skipChar=False,
            success=False,
            maxIndent=None,
            indentDelta=0,
            error=dict(
                name=None,
                message=None,
                lineNo=None,
                x=None,
            ),
            errorPosCache={},
        ))

        if isinstance(options, dict):
            if 'cursorDx' in options:
                self.cursorDx = options['cursorDx']
            if 'cursorLine' in options:
                self.cursorLine = options['cursorLine']
            if 'cursorX' in options:
                self.cursorX = options['cursorX']

    def cacheErrorPos(self, name, lineNo, x):
        self.errorPosCache[name] = {'lineNo': lineNo, 'x': x}

    def new_error(self, name, lineNo, x):
        if lineNo is None:
            lineNo = self.errorPosCache[name]['lineNo']
        if x is None:
            x = self.errorPosCache[name]['x']

        return {
            'parinferError': True,
            'name': name,
            'message': errorMessages[name],
            'lineNo': lineNo,
            'x': x,
        }

    # -------------------------------------------------------------------------------
    # Line Operations
    # -------------------------------------------------------------------------------

    def insertWithinLine(self, lineNo, idx, insert):
        line = self.lines[lineNo]
        self.lines[lineNo] = insertWithinString(line, idx, insert)

    def replaceWithinLine(self, lineNo, start, end, replace):
        line = self.lines[lineNo]
        self.lines[lineNo] = replaceWithinString(line, start, end, replace)

    def removeWithinLine(self, lineNo, start, end):
        line = self.lines[lineNo]
        self.lines[lineNo] = removeWithinString(line, start, end)

    def initLine(self, line):
        self.x = 0
        self.lineNo = self.lineNo + 1
        self.lines.append(line)

        # reset line-specific state
        self.commentX = None
        self.indentDelta = 0

    def commitChar(self, origCh):
        ch = self.ch
        if origCh != ch:
            self.replaceWithinLine(self.lineNo, self.x, self.x + len(origCh), ch)
        self.x = self.x + len(ch)

    def onOpenParen(self):
        if self.isInCode:
            self.parenStack.append({
                'lineNo': self.lineNo,
                'x': self.x,
                'ch': self.ch,
                'indentDelta': self.indentDelta,
            })

    def onMatchedCloseParen(self):
        opener = peek(self.parenStack)
        self.parenTrail['endX'] = self.x + 1
        self.parenTrail['openers'].append(opener)
        self.maxIndent = opener['x']
        self.parenStack.pop()

    def onUnmatchedCloseParen(self):
        self.ch = ''

    def onCloseParen(self):
        if self.isInCode:
            if isValidCloseParen(self.parenStack, self.ch):
                self.onMatchedCloseParen()
            else:
                self.onUnmatchedCloseParen()

    def onTab(self):
        if self.isInCode:
            self.ch = DOUBLE_SPACE

    def onSemicolon(self):
        if self.isInCode:
            self.isInComment = True
            self.commentX = self.x

    def onNewLine(self):
        self.isInComment = False
        self.ch = ''

    def onQuote(self):
        if self.isInStr:
            self.isInStr = False
        elif self.isInComment:
            self.quoteDanger = not self.quoteDanger
            if self.quoteDanger:
                self.cacheErrorPos(ERROR_QUOTE_DANGER, self.lineNo, self.x)
        else:
            self.isInStr = True
            self.cacheErrorPos(ERROR_UNCLOSED_QUOTE, self.lineNo, self.x)

    def onBackslash(self):
        self.isEscaping = True

    def afterBackslash(self):
        self.isEscaping = False

        if self.ch == NEWLINE:
            if self.isInCode:
                err = self.new_error(ERROR_EOL_BACKSLASH, self.lineNo, self.x - 1)
                raise ParinferError(err)
            self.onNewLine()

    CHAR_DISPATCH = {
        '(': onOpenParen,
        '{': onOpenParen,
        '[': onOpenParen,

        ')': onCloseParen,
        '}': onCloseParen,
        ']': onCloseParen,

        DOUBLE_QUOTE: onQuote,
        SEMICOLON: onSemicolon,
        BACKSLASH: onBackslash,
        TAB: onTab,
        NEWLINE: onNewLine,
    }

    def onChar(self):
        ch = self.ch

        if self.isEscaping:
            self.afterBackslash()
        else:
            charFn = self.CHAR_DISPATCH.get(ch, None)
            if charFn is not None:
                charFn(self)

        self.isInCode = (not self.isInComment and not self.isInStr)

    # -------------------------------------------------------------------------------
    # Cursor Functions
    # -------------------------------------------------------------------------------

    def isCursorOnLeft(self):
        return (self.lineNo == self.cursorLine and
                self.cursorX is not None and
                self.cursorX <= self.x)

    def isCursorOnRight(self, x):
        return (self.lineNo == self.cursorLine and
                self.cursorX is not None and
                x is not None and
                self.cursorX > x)

    def isCursorInComment(self):
        return self.isCursorOnRight(self.commentX)

    def handleCursorDelta(self):
        hasCursorDelta = (self.cursorDx is not None and
                          self.cursorLine == self.lineNo and
                          self.cursorX == self.x)

        if hasCursorDelta:
            self.indentDelta = self.indentDelta + self.cursorDx

    # -------------------------------------------------------------------------------
    # Paren Trail Functions
    # -------------------------------------------------------------------------------

    def updateParenTrailBounds(self):
        line = self.lines[self.lineNo]
        prevCh = None
        if self.x > 0:
            prevCh = line[self.x - 1]
        ch = self.ch

        shouldReset = (self.isInCode and
                       ch != "" and
                       ch not in CLOSE_PARENS and
                       (ch != BLANK_SPACE or prevCh == BACKSLASH) and
                       ch != DOUBLE_SPACE)

        if shouldReset:
            self.parenTrail['lineNo'] = self.lineNo
            self.parenTrail['startX'] = self.x + 1
            self.parenTrail['endX'] = self.x + 1
            self.parenTrail['openers'] = []
            self.maxIndent = None

    def clampParenTrailToCursor(self):
        startX = self.parenTrail['startX']
        endX = self.parenTrail['endX']

        isCursorClamping = (self.isCursorOnRight(startX) and
                            not self.isCursorInComment())

        if isCursorClamping:
            newStartX = max(startX, self.cursorX)
            newEndX = max(endX, self.cursorX)

            line = self.lines[self.lineNo]
            removeCount = 0
            for i in range(startX, newStartX):
                if line[i] in CLOSE_PARENS:
                    removeCount = removeCount + 1

            for i in range(removeCount):
                self.parenTrail['openers'].pop(0)
            self.parenTrail['startX'] = newStartX
            self.parenTrail['endX'] = newEndX

    def removeParenTrail(self):
        startX = self.parenTrail['startX']
        endX = self.parenTrail['endX']

        if startX == endX:
            return

        openers = self.parenTrail['openers']
        while len(openers) != 0:
            self.parenStack.append(openers.pop())

        self.removeWithinLine(self.lineNo, startX, endX)

    def correctParenTrail(self, indentX):
        parens = ""

        while len(self.parenStack) > 0:
            opener = peek(self.parenStack)
            if opener['x'] >= indentX:
                self.parenStack.pop()
                parens = parens + PARENS[opener['ch']]
            else:
                break

        self.insertWithinLine(self.parenTrail['lineNo'], self.parenTrail['startX'], parens)

    def cleanParenTrail(self):
        startX = self.parenTrail['startX']
        endX = self.parenTrail['endX']

        if (startX == endX or self.lineNo != self.parenTrail['lineNo']):
            return

        line = self.lines[self.lineNo]
        newTrail = ""
        spaceCount = 0
        for i in range(startX, endX):
            if line[i] in CLOSE_PARENS:
                newTrail = newTrail + line[i]
            else:
                spaceCount = spaceCount + 1

        if spaceCount > 0:
            self.replaceWithinLine(self.lineNo, startX, endX, newTrail)
            self.parenTrail['endX'] = self.parenTrail['endX'] - spaceCount

    def appendParenTrail(self):
        opener = self.parenStack.pop()
        closeCh = PARENS[opener['ch']]

        self.maxIndent = opener['x']
        self.insertWithinLine(self.parenTrail['lineNo'], self.parenTrail['endX'], closeCh)
        self.parenTrail['endX'] = self.parenTrail['endX'] + 1

    def finishNewParenTrail(self):
        if self.mode == INDENT_MODE:
            self.clampParenTrailToCursor()
            self.removeParenTrail()
        elif self.mode == PAREN_MODE:
            if self.lineNo != self.cursorLine:
                self.cleanParenTrail()

    # -------------------------------------------------------------------------------
    # Indentation functions
    # -------------------------------------------------------------------------------

    def correctIndent(self):
        origIndent = self.x
        newIndent = origIndent
        minIndent = 0
        maxIndent = self.maxIndent

        opener = peek(self.parenStack)
        if opener is not None:
            minIndent = opener['x'] + 1
            newIndent = newIndent + opener['indentDelta']

        newIndent = clamp(newIndent, minIndent, maxIndent)

        if newIndent != origIndent:
            indentStr = repeatString(BLANK_SPACE, newIndent)
            self.replaceWithinLine(self.lineNo, 0, origIndent, indentStr)
            self.x = newIndent
            self.indentDelta = self.indentDelta + newIndent - origIndent

    def onProperIndent(self):
        self.trackingIndent = False

        if self.quoteDanger:
            err = self.new_error(ERROR_QUOTE_DANGER, None, None)
            raise ParinferError(err)

        if self.mode == INDENT_MODE:
            self.correctParenTrail(self.x)
        elif self.mode == PAREN_MODE:
            self.correctIndent()

    def onLeadingCloseParen(self):
        self.skipChar = True
        self.trackingIndent = True

        if self.mode == PAREN_MODE:
            if isValidCloseParen(self.parenStack, self.ch):
                if self.isCursorOnLeft():
                    self.skipChar = False
                    self.onProperIndent()
                else:
                    self.appendParenTrail()

    def onIndent(self):
        if self.ch in CLOSE_PARENS:
            self.onLeadingCloseParen()
        elif self.ch == SEMICOLON:
            # comments don't count as indentation points
            self.trackingIndent = False
        elif self.ch != NEWLINE:
            self.onProperIndent()

    # -------------------------------------------------------------------------------
    # High-level processing functions
    # -------------------------------------------------------------------------------

    def processChar(self, ch):
        origCh = ch

        self.ch = ch
        self.skipChar = False

        if self.mode == PAREN_MODE:
            self.handleCursorDelta()

        if self.trackingIndent and ch != BLANK_SPACE and ch != TAB:
            self.onIndent()

        if self.skipChar:
            self.ch = ""
        else:
            self.onChar()
            self.updateParenTrailBounds()

        self.commitChar(origCh)

    def processLine(self, line):
        self.initLine(line)

        if self.mode == INDENT_MODE:
            self.trackingIndent = (len(self.parenStack) != 0 and
                                   not self.isInStr)
        elif self.mode == PAREN_MODE:
            self.trackingIndent = not self.isInStr

        chars = line + NEWLINE
        for c in chars:
            self.processChar(c)

        if self.lineNo == self.parenTrail['lineNo']:
            self.finishNewParenTrail()

    def finalizeResult(self):
        if self.quoteDanger:
            err = self.new_error(ERROR_QUOTE_DANGER, None, None)
            raise ParinferError(err)

        if self.isInStr:
            err = self.new_error(ERROR_UNCLOSED_QUOTE, None, None)
            raise ParinferError(err)

        if len(self.parenStack) != 0:
            if self.mode == PAREN_MODE:
                opener = peek(self.parenStack)
                err = self.new_error(ERROR_UNCLOSED_PAREN, opener['lineNo'], opener['x'])
                raise ParinferError(err)
            elif self.mode == INDENT_MODE:
                self.correctParenTrail(0)

        self.success = True

    def processError(self, e):
        self.success = False
        if e['parinferError']:
            del e['parinferError']
            self.error = e
        else:
            self.error['name'] = ERROR_UNHANDLED
            self.error['message'] = e['stack']

    # -------------------------------------------------------------------------------
    # Public API Helpers
    # -------------------------------------------------------------------------------

    def getChangedLines(self):
        changedLines = []
        for i in range(len(self.lines)):
            if self.lines[i] != self.origLines[i]:
                changedLines.append({
                    'lineNo': i,
                    'line': self.lines[i],
                })
        return changedLines

    def publicResult(self):
        if not self.success:
            return {
                'text': self.origText,
                'success': False,
                'error': self.error,
            }

        lineEnding = getLineEnding(self.origText)
        return {
            'text': lineEnding.join(self.lines),
            'success': True,
            'changedLines': self.getChangedLines(),
        }


# -------------------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------------------

def indent_mode(text, options):
    result = processText(text, options, INDENT_MODE)
    return result.publicResult()


def paren_mode(text, options):
    result = processText(text, options, PAREN_MODE)
    return result.publicResult()
