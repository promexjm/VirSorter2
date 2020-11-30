#!/usr/bin/env python

import sys
import os
from collections import Counter
import screed
import pandas as pd
import numpy as np
import click

script_dir = os.path.dirname(os.path.abspath(__file__))
snakefile_dir = os.path.dirname(script_dir)
pkg_dir = os.path.dirname(snakefile_dir)
sys.path.append(pkg_dir)
from virsorter.config import get_default_config, set_logger
from virsorter.utils import (
        load_rbs_category, df_tax_per_config, parse_gff, 
        extract_feature_tax, parse_hallmark_hmm, AFFI_CONTIG_COLS,
        TAX_FEATURE_LIST, GFF_PARSER_COLS, GENE_ANNO_COLS, TAXON_LIST
)

DEFAULT_CONFIG = get_default_config()

CONTEXT_SETTINGS = {'help_option_names': ['-h', '--help']}
@click.command(context_settings=CONTEXT_SETTINGS)

@click.option('--pfamtax', default=None, 
        help=('list of tables with best hit of each gene, bit score, and '
            'taxonomy using pfam viral hmm from diff virla groups')
)
@click.argument('seqfile', type=click.Path())
@click.argument('outfile', type=click.Path())
@click.argument('affi-contigs-file', type=click.Path())
@click.argument('gff')
@click.argument('tax')
@click.argument('group')
def main(seqfile, outfile, gff, tax, group,
        affi_contigs_file, pfamtax):
    '''Add sequence length to table

    \b
    Example:
        python make-affi-contigs-tabfile.py
                --pfamtax-list
                    "A/<all.pdg.hmm.pfamtax>,B/<all.pdg.hmm.pfamtax>"
                <viral-combined.fa>
                <viral-gene-annotation.tsv>
                <affi-contigs.tab>
                "A/<all.pdg.gff>,B/<all.pdg.gff>"
                "A/<all.pdg.hmm.tax>,B/<all.pdg.hmm.tax>"
                "A,B"


        \b
        <viral-combined.fa>: viral contigs with less than
                two genes and hallmark gene
        <viral-gene-annotation.tsv>: viral gene annotation table
        <affi-contigs.tab>: output affi-contigs.tab file for DRAM-v
        <all.pdg.gff>: gff file from prodigal
        <all.pdg.hmm.tax>: table with best hit of each gene, bit score, 
                and taxonomy using customized viral hmm db
        <all.pdg.hmm.pfamtax>: table with best hit of each gene, bit score, 
                and taxonomy using pfam viral hmm
        A: viral group name


    '''

    seqfile = seqfile
    affi_f = affi_contigs_file

    d_group2name = {}
    d_name2provirus = {}
    with screed.open(seqfile) as sp:
        for rec in sp:
            header = rec.name
            name, desc = header.split(None ,1)
            # remove suffix, ty in ['full', '*_partial', 'lt2gene']
            name, ty = name.rsplit('||', 1)
            provirus = False
            if ty.endswith('partial'):
                provirus = True
            d_name2provirus[name] = provirus
            _d = dict(i.split(':') for i in desc.split('||'))
            best_group = _d['group']
            st = d_group2name.setdefault(best_group, set())
            st.add(name)

    name_st = d_group2name.get(group, set())
    # no seq has best score in this group; just exit
    if len(name_st) == 0:
        with open(affi_f, 'w') as fw_affi, open(outfile, 'w') as fw_anno:
            mes = GFF_PARSER_COLS + GENE_ANNO_COLS + ['seqname_final']
            fw_anno.write('%s\n'.format('\t'.join(mes)))
        return

    gene_anno_lis = []
    orf_index_ind = GFF_PARSER_COLS.index('orf_index')
    seqname_ind = GFF_PARSER_COLS.index('seqname')

    gff_f, tax_f, group = gff, tax, group
    gen_gff = parse_gff(gff_f) 

    if pfamtax != None:
        pfamtax_f = pfamtax

    prev_seqname = None
    for l in gen_gff:
        seqname = l[0]
        # remove rbs info
        seqname_ori = seqname.rsplit('||', 1)[0]
        if not seqname_ori in name_st:
            continue

        if seqname != prev_seqname:
            df_tax_sel = df_tax_per_config(tax_f, seqname, taxwhm=True)
            if  pfamtax != None:
                df_pfamtax_sel = df_tax_per_config(pfamtax_f, seqname)

        orf_index = l[orf_index_ind]
        sel = (df_tax_sel['orf_index'] == orf_index)
        ser = df_tax_sel.loc[sel, :].squeeze()
        if len(ser) == 0:
            tax = 'unaligned'
            hmm = 'NA'
            score = np.nan
            hallmark = 0
        else:
            tax = ser.loc['tax']
            hmm = ser.loc['hmm']
            score = ser.loc['score']
            hallmark = int(ser.loc['hallmark'])

        # pfamtax
        if pfamtax != None:
            sel = (df_pfamtax_sel['orf_index'] == orf_index)
            ser = df_pfamtax_sel.loc[sel, :].squeeze()
            if len(ser) == 0:
                pfamtax = 'unaligned'
                pfamhmm = 'NA'
                pfamscore = np.nan
            else:
                pfamtax = ser.loc['tax']
                pfamhmm = ser.loc['hmm']
                pfamscore = ser.loc['score']
        else:
            pfamhmm = 'NA'

        provirus = d_name2provirus[seqname_ori]
        is_hallmark = 0
        if not provirus:
            if hallmark == 1:
                cat = 0
                is_hallmark = 1
            elif tax == 'vir':
                cat = 1
            else:
                cat = 2

        else:
            if hallmark == 1:
                cat = 0
                is_hallmark = 1
            elif tax == 'vir':
                cat = 1
            else:
                cat = 2

        _l = list(l)
        _l[seqname_ind] = seqname_ori
        bits = score
        _l.extend(
            [hmm, bits, pfamhmm, pfamscore, tax, is_hallmark, cat, group]
        )
        gene_anno_lis.append(_l)
        prev_seqname = seqname

    # no seqs in this gff (split) has best score in this group; just exit
    if len(gene_anno_lis) == 0:
        with open(affi_f, 'w') as fw_affi, open(outfile, 'w') as fw_anno:
            mes = GFF_PARSER_COLS + GENE_ANNO_COLS + ['seqname_final']
            fw_anno.write('%s\n'.format('\t'.join(mes)))
        return

    df_anno = pd.DataFrame(gene_anno_lis, 
            columns=(GFF_PARSER_COLS + GENE_ANNO_COLS))

    st_seqname_anno = set(df_anno['seqname'])
    df_lis = []
    with screed.open(seqfile) as sp, open(affi_f, 'w') as fw:
        for rec in sp:
            header = rec.name
            name, desc = header.split(None ,1)
            # remove full, _provirus suffix
            seqname, ty = name.rsplit('||', 1)
            if not seqname in st_seqname_anno:
                continue

            d_desc = dict(i.split(':') for i in desc.split('||'))
            shape = d_desc['shape']
            start_ind = d_desc['start_ind']
            end_ind = d_desc['end_ind']
            best_group = d_desc['group']

            _sel = ((df_anno['group'] == best_group) & 
                    (df_anno['seqname'] == seqname))

            _df = df_anno.loc[_sel, :]  # genes for only one seqname
            if start_ind == 'nan' or end_ind == 'nan':
                df_oneseq = _df
            else:
                _sel2 = ((_df['orf_index'] >= int(start_ind)) & 
                            (_df['orf_index'] <= int(end_ind)))
                df_oneseq = _df.loc[_sel2,:]

            df_oneseq = df_oneseq.copy()
            df_oneseq['seqname_final'] = name
            df_lis.append(df_oneseq)

            # within contigs-affi.tsv
            # no | allowed in name (the string after >) for DRAM-v
            # no | allowed in gene_name for DRAM-v
            name = name.replace('|', '_')
            gene_nb = len(df_oneseq)
            shape_simple = 'c' if shape == 'circular' else 'l'

            fw.write(f'>{name}|{gene_nb}|{shape_simple}\n')
            for i in range(len(df_oneseq)):
                ser = df_oneseq.iloc[i]
                orf_ind = ser.loc['orf_index']
                gene_name = f'{name}__{orf_ind}'
                l = [gene_name]
                # skip gene_name
                for i in AFFI_CONTIG_COLS[1:]:
                    try:
                        j = ser.loc[i]
                    except KeyError as e:
                        j = np.nan

                    if j in set(['NA', np.nan]):
                        j = '-'

                    l.append(str(j))

                gene_row_str = '|'.join(l)
                fw.write(f'{gene_row_str}\n')

        df_merge = pd.concat(df_lis)
        df_merge.to_csv(outfile, sep='\t', index=False, na_rep='nan')

if __name__ == '__main__':
    main()
