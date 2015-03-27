#!/usr/bin/env python

from __future__ import unicode_literals

import argparse
import collections
import locale
import string
import sys

import flatcat
from flatcat.exception import ArgumentException
from flatcat import utils


PY3 = sys.version_info.major == 3

LICENSE = """
Copyright (c) 2015, Stig-Arne Gronroos
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

1.  Redistributions of source code must retain the above copyright
    notice, this list of conditions and the following disclaimer.

2.  Redistributions in binary form must reproduce the above
    copyright notice, this list of conditions and the following
    disclaimer in the documentation and/or other materials provided
    with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
"""

def get_argparser():
    parser = argparse.ArgumentParser(
        prog='flatcat-advanced-segment',
        description="""
Morfessor FlatCat advanced segmentation and reformatting
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False)
    add_arg = parser.add_argument
    add_arg('infile', metavar='<infile>',
            help='The input file. The type will be sniffed automatically, '
                 'or can be specified manually.')
    add_arg('outfile', metavar='<outfile>',
            help='The output file. The type is defined by preset '
                 'or can be specified manually.')
    add_arg('-m', '--model', dest='model', metavar='<flatcat model>',
            help='A FlatCat model (tarball or binary), '
                 'for the operations that require a model to work.')

    add_arg('-e', '--encoding', dest='encoding', metavar='<encoding>',
            help='Encoding of input and output files (if none is given, '
                 'both the local encoding and UTF-8 are tried).')

    add_arg('--input-column-separator', dest='cseparator', type=str,
            default=None, metavar='<regexp>',
            help='Manually set input column separator regexp.')
    add_arg('--input-morph-separator', dest='consseparator', type=str,
            default=None, metavar='<string>',
            help='Manually set input morph (construction) separator string.')
    add_arg('--input-category-separator', dest='catseparator', type=str,
            default=None, metavar='<regexp>',
            help='Manually set input morph category tag separator. ')

    add_arg('--output-format', dest='outputformat', type=str,
            default=r'{analysis}\n',  # FIXME
            metavar='<format>',
            help='Format string for --output file (default: "%(default)s"). '
                 'Valid keywords are: '
                 '{analysis} = morphs of the word, '
                 '{compound} = word, '
                 '{count} = count of the word (currently always 1), and '
                 '{logprob} = log-probability of the analysis. Valid escape '
                 'sequences are "\\n" (newline) and "\\t" (tabular)')
    add_arg('--output-morph-separator', dest='outputconseparator',
            type=str, default=None, metavar='<str>',
            help='Construction separator for analysis in output.')
    add_arg('--output-category-separator', dest='outputtagseparator',
            type=str, default=None, metavar='<str>',
            help='Category tag separator for analysis in --output file ')
    add_arg('--strip-categories', dest='striptags', default=False,
            action='store_true',
            help='Remove tags if present in the input')
    add_arg('--output-newlines', dest='outputnewlines', default=False,
            action='store_true',
            help='For each newline in input, print newline in --output file '
            '(default: "%(default)s")')


    add_arg('--remove-nonmorphemes', dest='rm_nonmorph', default=False,
            action='store_true',
            help='Use heuristic postprocessing to remove nonmorphemes '
                 'from output segmentations.')

    add_arg('--restitch', dest='restitch',
            default=False, action='store_true',
            help='When given a segmented corpus, '
                 'output the recombined surface forms.')
    
    return parser


IntermediaryFormat = collections.namedtuple('IntermediaryFormat',
    ['count', 'word', 'analysis', 'logp', 'clogp'])

# FIXME sniffer:
# columns? type of first whitespace? mix of spaces and tabs?
# is first column a number?
# is there a known morph delimiter?
# is there a known category delimiter? category tags?
# is the first column a concatenation of later morphs?

# FIXME: adding and removing morphs from the analysis (no longer concatenative)
# FIXME: joining some morphs depending on tags (e.g. join compound modifier)
# FIXME: different delimiters for different surrounding tags
# FIXME: restitching

class FlatcatWrapper(object):
    def __init__(self, model, remove_nonmorphemes=True, clogp=False):
        self.model = model
        if remove_nonmorphemes:
            self.hpp = flatcat.categorizationscheme.HeuristicPostprocessor()
        else:
            self.hpp = None
        self.clogp = clogp

    def segment(self, word):
        (analysis, cost) = self.model.viterbi_analyze(word.word)
        if self.hpp is not None:
            analysis = self.hpp.remove_nonmorphemes(analysis, self.model)
        if self.clogp:
            clogp = self.model.forward_logprob(word)
        else:
            clogp = 0
        return IntermediaryFormat(
            word.count,
            word.word,
            analysis,
            cost,
            clogp)


class AnalysisFormatter(object):
    def __init__(self,
                 morph_sep=' + ',   # can also be func(tag, tag)
                 category_sep='/',
                 strip_tags=False):
        if utils._is_string(morph_sep):
            def morph_sep_func(left, right):
                if (left == flatcat.WORD_BOUNDARY or
                        right == flatcat.WORD_BOUNDARY):
                    return ''
                else:
                    return morph_sep
            self._morph_sep = morph_sep_func
        else:
            self._morph_sep = morph_sep
        self.category_sep = category_sep
        self.strip_tags = strip_tags
        self._morph_formatter = self._make_morph_formatter(category_sep,
                                                           strip_tags)

    def segment(self, word):
        analysis = flatcat.flatcat._wb_wrap(word.analysis)
        out = []
        for (i, cmorph) in enumerate(analysis):
            out.append(self._morph_sep(
                analysis[i - 1].category,
                cmorph.category))
            if cmorph.category == flatcat.WORD_BOUNDARY:
                continue
            out.append(self._morph_formatter(cmorph))
        return ''.join(out)


    def _make_morph_formatter(self, category_sep, strip_tags):
        if not strip_tags:
            def output_morph(cmorph):
                if cmorph.category is None:
                    return cmorph.morph
                return '{}{}{}'.format(cmorph.morph,
                                        category_sep,
                                        cmorph.category)
        else:
            def output_morph(cmorph):
                try:
                    return cmorph.morph
                except AttributeError:
                    return cmorph
        return output_morph


# FIXME: has nothing specificly with segmentation to do: rename
class SegmentationCache(object):
    def __init__(self, seg_func, limit=1000000):
        self.seg_func = seg_func
        self.limit = limit
        self._cache = {}

    def segment(self, word):
        if len(self._cache) > self.limit:
            # brute solution clears whole cache once limit is reached
            self._cache = {}
        if word not in self._cache:
            self._cache[word] = self.seg_func(word)
        return self._cache[word]


def load_model(io, modelfile):
    init_is_pickle = (modelfile.endswith('.pickled') or
                      modelfile.endswith('.pickle') or
                      modelfile.endswith('.bin'))

    init_is_tarball = (modelfile.endswith('.tar.gz') or
                       modelfile.endswith('.tgz'))
    if not init_is_pickle and not init_is_tarball:
        raise ArgumentException(
            'This tool can only load tarball and binary models')

    if init_is_pickle:
        model = io.read_binary_model_file(modelfile)
    else:
        model = io.read_tarball_model_file(modelfile)
    model.initialize_hmm()
    return model

# FIXME: these should be in utils?
_preferred_encoding = locale.getpreferredencoding()


# FIXME: these should be in utils?
def _locale_decoder(s):
    """ Decodes commandline input in locale """
    return unicode(s.decode(_preferred_encoding))


# FIXME: should be part of sniffer?
# FIXME: input format overrides not used atm
def dummy_reader(io, infile):
    for item in io.read_corpus_file(infile):
        (count, compound, atoms) = item
        yield IntermediaryFormat(
            count,
            compound,
            atoms,
            0, 0)


def main(args):
    io = flatcat.io.FlatcatIO(encoding=args.encoding)
    model = load_model(io, args.model)  # FIXME not always

    outformat = args.outputformat
    csep = args.outputconseparator
    tsep = args.outputtagseparator
    if not PY3:
        outformat = _locale_decoder(outformat)
        csep = _locale_decoder(csep)
        tsep = _locale_decoder(tsep)
    outformat = outformat.replace(r"\n", "\n")
    outformat = outformat.replace(r"\t", "\t")
    keywords = [x[1] for x in string.Formatter().parse(outformat)]

    # chain of functions to apply to each item
    item_steps = []

    model_wrapper = FlatcatWrapper(
        model,
        remove_nonmorphemes=args.rm_nonmorph,
        clogp=('clogprob' in keywords))
    item_steps.append(model_wrapper.segment)

    analysis_formatter = AnalysisFormatter(
        csep,   # FIXME
        tsep,
        args.striptags)
    item_steps.append(analysis_formatter.segment)

    def process_item(item):
        for func in item_steps:
            item = func(item)
        return item

    cache = SegmentationCache(process_item)

    with io._open_text_file_write(args.outfile) as fobj:
        pipe = dummy_reader(io, args.infile)
        pipe = utils._generator_progress(pipe)
        for item in pipe:
            if len(item.analysis) == 0: 
                # is a corpus newline marker
                if args.outputnewlines:
                    fobj.write("\n")
                continue
            item = cache.segment(item)
            fobj.write(outformat.format(
                    count=item.count,
                    compound=item.word,
                    analysis=item.analysis,
                    logprob=item.logp,
                    clogprob=item.clogp))


if __name__ == "__main__":
    parser = get_argparser()
    try:
        args = parser.parse_args(sys.argv[1:])
        main(args)
    except ArgumentException as e:
        parser.error(e)
    except Exception as e:
        raise