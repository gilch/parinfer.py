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

def insert_within_string(orig, idx, insert):
    return orig[:idx] + insert + orig[idx:]


def replace_within_string(orig, start, end, replace):
    return orig[:start] + replace + orig[end:]


def remove_within_string(orig, start, end):
    return orig[:start] + orig[end:]


def repeat_string(text, n):
    return text * n


# NOTE: We assume that if the CR char "\r" is used anywhere, we should use CRLF
#       line-endings after every line.
def get_line_ending(text):
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

def clamp(val_n, min_n, max_n):
    if min_n is not None:
        val_n = max(min_n, val_n)
    if max_n is not None:
        val_n = min(max_n, val_n)
    return val_n


def peek(arr):
    return arr[-1] if arr else None


# -------------------------------------------------------------------------------
# Character Functions
# -------------------------------------------------------------------------------

def is_valid_close_paren(paren_stack, ch):
    if len(paren_stack) == 0:
        return False
    return peek(paren_stack)['ch'] == PARENS[ch]


def process_text(text, options, mode):
    result = Result(text, options, mode)

    try:
        for line in result.origLines:
            result.process_line(line)
        result.finalize_result()
    except ParinferError as e:
        error_details = e.args[0]
        result.process_error(error_details)

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

    def cache_error_pos(self, name, line_no, x):
        self.errorPosCache[name] = {'lineNo': line_no, 'x': x}

    def new_error(self, name, line_no, x):
        if line_no is None:
            line_no = self.errorPosCache[name]['lineNo']
        if x is None:
            x = self.errorPosCache[name]['x']

        return {
            'parinferError': True,
            'name': name,
            'message': errorMessages[name],
            'lineNo': line_no,
            'x': x,
        }

    # -------------------------------------------------------------------------------
    # Line Operations
    # -------------------------------------------------------------------------------

    def insert_within_line(self, line_no, idx, insert):
        line = self.lines[line_no]
        self.lines[line_no] = insert_within_string(line, idx, insert)

    def replace_within_line(self, line_no, start, end, replace):
        line = self.lines[line_no]
        self.lines[line_no] = replace_within_string(line, start, end, replace)

    def remove_within_line(self, line_no, start, end):
        line = self.lines[line_no]
        self.lines[line_no] = remove_within_string(line, start, end)

    def init_line(self, line):
        self.x = 0
        self.lineNo += 1
        self.lines.append(line)

        # reset line-specific state
        self.commentX = None
        self.indentDelta = 0

    def commit_char(self, orig_ch):
        ch = self.ch
        if orig_ch != ch:
            self.replace_within_line(self.lineNo, self.x, self.x + len(orig_ch), ch)
        self.x += len(ch)

    def on_open_paren(self):
        if self.isInCode:
            self.parenStack.append({
                'lineNo': self.lineNo,
                'x': self.x,
                'ch': self.ch,
                'indentDelta': self.indentDelta,
            })

    def on_matched_close_paren(self):
        opener = peek(self.parenStack)
        self.parenTrail['endX'] = self.x + 1
        self.parenTrail['openers'].append(opener)
        self.maxIndent = opener['x']
        self.parenStack.pop()

    def on_unmatched_close_paren(self):
        self.ch = ''

    def on_close_paren(self):
        if self.isInCode:
            if is_valid_close_paren(self.parenStack, self.ch):
                self.on_matched_close_paren()
            else:
                self.on_unmatched_close_paren()

    def on_tab(self):
        if self.isInCode:
            self.ch = DOUBLE_SPACE

    def on_semicolon(self):
        if self.isInCode:
            self.isInComment = True
            self.commentX = self.x

    def on_new_line(self):
        self.isInComment = False
        self.ch = ''

    def on_quote(self):
        if self.isInStr:
            self.isInStr = False
        elif self.isInComment:
            self.quoteDanger = not self.quoteDanger
            if self.quoteDanger:
                self.cache_error_pos(ERROR_QUOTE_DANGER, self.lineNo, self.x)
        else:
            self.isInStr = True
            self.cache_error_pos(ERROR_UNCLOSED_QUOTE, self.lineNo, self.x)

    def on_backslash(self):
        self.isEscaping = True

    def after_backslash(self):
        self.isEscaping = False

        if self.ch == NEWLINE:
            if self.isInCode:
                err = self.new_error(ERROR_EOL_BACKSLASH, self.lineNo, self.x - 1)
                raise ParinferError(err)
            self.on_new_line()

    CHAR_DISPATCH = {
        '(': on_open_paren,
        '{': on_open_paren,
        '[': on_open_paren,

        ')': on_close_paren,
        '}': on_close_paren,
        ']': on_close_paren,

        DOUBLE_QUOTE: on_quote,
        SEMICOLON: on_semicolon,
        BACKSLASH: on_backslash,
        TAB: on_tab,
        NEWLINE: on_new_line,
    }

    def on_char(self):
        ch = self.ch

        if self.isEscaping:
            self.after_backslash()
        else:
            char_fn = self.CHAR_DISPATCH.get(ch, None)
            if char_fn is not None:
                char_fn(self)

        self.isInCode = (not self.isInComment and not self.isInStr)

    # -------------------------------------------------------------------------------
    # Cursor Functions
    # -------------------------------------------------------------------------------

    def is_cursor_on_left(self):
        return (self.lineNo == self.cursorLine and
                self.cursorX is not None and
                self.cursorX <= self.x)

    def is_cursor_on_right(self, x):
        return (self.lineNo == self.cursorLine and
                self.cursorX is not None and
                x is not None and
                self.cursorX > x)

    def is_cursor_in_comment(self):
        return self.is_cursor_on_right(self.commentX)

    def handle_cursor_delta(self):
        has_cursor_delta = (self.cursorDx is not None and
                          self.cursorLine == self.lineNo and
                          self.cursorX == self.x)

        if has_cursor_delta:
            self.indentDelta = self.indentDelta + self.cursorDx

    # -------------------------------------------------------------------------------
    # Paren Trail Functions
    # -------------------------------------------------------------------------------

    def update_paren_trail_bounds(self):
        line = self.lines[self.lineNo]
        prev_ch = None
        if self.x > 0:
            prev_ch = line[self.x - 1]
        ch = self.ch

        should_reset = (self.isInCode and
                       ch != "" and
                       ch not in CLOSE_PARENS and
                       (ch != BLANK_SPACE or prev_ch == BACKSLASH) and
                       ch != DOUBLE_SPACE)

        if should_reset:
            self.parenTrail['lineNo'] = self.lineNo
            self.parenTrail['startX'] = self.x + 1
            self.parenTrail['endX'] = self.x + 1
            self.parenTrail['openers'] = []
            self.maxIndent = None

    def clamp_paren_trail_to_cursor(self):
        start_x = self.parenTrail['startX']
        end_x = self.parenTrail['endX']

        is_cursor_clamping = (self.is_cursor_on_right(start_x) and
                            not self.is_cursor_in_comment())

        if is_cursor_clamping:
            new_start_x = max(start_x, self.cursorX)
            new_end_x = max(end_x, self.cursorX)

            line = self.lines[self.lineNo]
            remove_count = 0
            for i in range(start_x, new_start_x):
                if line[i] in CLOSE_PARENS:
                    remove_count += 1

            for i in range(remove_count):
                self.parenTrail['openers'].pop(0)
            self.parenTrail['startX'] = new_start_x
            self.parenTrail['endX'] = new_end_x

    def remove_paren_trail(self):
        start_x = self.parenTrail['startX']
        end_x = self.parenTrail['endX']

        if start_x == end_x:
            return

        openers = self.parenTrail['openers']
        while len(openers) != 0:
            self.parenStack.append(openers.pop())

        self.remove_within_line(self.lineNo, start_x, end_x)

    def correct_paren_trail(self, indent_x):
        parens = ""

        while len(self.parenStack) > 0:
            opener = peek(self.parenStack)
            if opener['x'] >= indent_x:
                self.parenStack.pop()
                parens += PARENS[opener['ch']]
            else:
                break

        self.insert_within_line(self.parenTrail['lineNo'], self.parenTrail['startX'], parens)

    def clean_paren_trail(self):
        start_x = self.parenTrail['startX']
        end_x = self.parenTrail['endX']

        if start_x == end_x or self.lineNo != self.parenTrail['lineNo']:
            return

        line = self.lines[self.lineNo]
        new_trail = ""
        space_count = 0
        for i in range(start_x, end_x):
            if line[i] in CLOSE_PARENS:
                new_trail = new_trail + line[i]
            else:
                space_count += 1

        if space_count > 0:
            self.replace_within_line(self.lineNo, start_x, end_x, new_trail)
            self.parenTrail['endX'] = self.parenTrail['endX'] - space_count

    def append_paren_trail(self):
        opener = self.parenStack.pop()
        close_ch = PARENS[opener['ch']]

        self.maxIndent = opener['x']
        self.insert_within_line(self.parenTrail['lineNo'], self.parenTrail['endX'], close_ch)
        self.parenTrail['endX'] += 1

    def finish_new_paren_trail(self):
        if self.mode == INDENT_MODE:
            self.clamp_paren_trail_to_cursor()
            self.remove_paren_trail()
        elif self.mode == PAREN_MODE:
            if self.lineNo != self.cursorLine:
                self.clean_paren_trail()

    # -------------------------------------------------------------------------------
    # Indentation functions
    # -------------------------------------------------------------------------------

    def correct_indent(self):
        orig_indent = self.x
        new_indent = orig_indent
        min_indent = 0
        max_indent = self.maxIndent

        opener = peek(self.parenStack)
        if opener is not None:
            min_indent = opener['x'] + 1
            new_indent = new_indent + opener['indentDelta']

        new_indent = clamp(new_indent, min_indent, max_indent)

        if new_indent != orig_indent:
            indent_str = repeat_string(BLANK_SPACE, new_indent)
            self.replace_within_line(self.lineNo, 0, orig_indent, indent_str)
            self.x = new_indent
            self.indentDelta = self.indentDelta + new_indent - orig_indent

    def on_proper_indent(self):
        self.trackingIndent = False

        if self.quoteDanger:
            err = self.new_error(ERROR_QUOTE_DANGER, None, None)
            raise ParinferError(err)

        if self.mode == INDENT_MODE:
            self.correct_paren_trail(self.x)
        elif self.mode == PAREN_MODE:
            self.correct_indent()

    def on_leading_close_paren(self):
        self.skipChar = True
        self.trackingIndent = True

        if self.mode == PAREN_MODE:
            if is_valid_close_paren(self.parenStack, self.ch):
                if self.is_cursor_on_left():
                    self.skipChar = False
                    self.on_proper_indent()
                else:
                    self.append_paren_trail()

    def on_indent(self):
        if self.ch in CLOSE_PARENS:
            self.on_leading_close_paren()
        elif self.ch == SEMICOLON:
            # comments don't count as indentation points
            self.trackingIndent = False
        elif self.ch != NEWLINE:
            self.on_proper_indent()

    # -------------------------------------------------------------------------------
    # High-level processing functions
    # -------------------------------------------------------------------------------

    def process_char(self, ch):
        orig_ch = ch

        self.ch = ch
        self.skipChar = False

        if self.mode == PAREN_MODE:
            self.handle_cursor_delta()

        if self.trackingIndent and ch != BLANK_SPACE and ch != TAB:
            self.on_indent()

        if self.skipChar:
            self.ch = ""
        else:
            self.on_char()
            self.update_paren_trail_bounds()

        self.commit_char(orig_ch)

    def process_line(self, line):
        self.init_line(line)

        if self.mode == INDENT_MODE:
            self.trackingIndent = (len(self.parenStack) != 0 and
                                   not self.isInStr)
        elif self.mode == PAREN_MODE:
            self.trackingIndent = not self.isInStr

        chars = line + NEWLINE
        for c in chars:
            self.process_char(c)

        if self.lineNo == self.parenTrail['lineNo']:
            self.finish_new_paren_trail()

    def finalize_result(self):
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
                self.correct_paren_trail(0)

        self.success = True

    def process_error(self, e):
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

    def get_changed_lines(self):
        changed_lines = []
        for i in range(len(self.lines)):
            if self.lines[i] != self.origLines[i]:
                changed_lines.append({
                    'lineNo': i,
                    'line': self.lines[i],
                })
        return changed_lines

    def public_result(self):
        if not self.success:
            return {
                'text': self.origText,
                'success': False,
                'error': self.error,
            }

        line_ending = get_line_ending(self.origText)
        return {
            'text': line_ending.join(self.lines),
            'success': True,
            'changedLines': self.get_changed_lines(),
        }


# -------------------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------------------

def indent_mode(text, options):
    result = process_text(text, options, INDENT_MODE)
    return result.public_result()


def paren_mode(text, options):
    result = process_text(text, options, PAREN_MODE)
    return result.public_result()
