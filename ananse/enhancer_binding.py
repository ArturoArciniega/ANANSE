import os
import tempfile
import shutil

import dask.dataframe as dd
import dask.diagnostics
import genomepy
from gimmemotifs.scanner import Scanner
from gimmemotifs.motif import read_motifs
from gimmemotifs.utils import as_fasta, pfmfile_location
import numpy as np
import pandas as pd
import pickle
from scipy import stats
from sklearn.preprocessing import minmax_scale
from tqdm import tqdm

from ananse.utils import bed_sort, bed_merge, count_reads, bam_index, bam_merge, bam_sort
from ananse.distributions import Distributions


def is_narrowpeak(bed, check_values=True):
    """
    Check BED type by column count.
    Check if peak values are not all zeroes unless check_values is False.

    Accepts a BED file (including narrowPeak, broadPeak, etc.)
    Returns bool
    """
    with open(bed) as b:
        for n, line in enumerate(b):
            if line.startswith("#"):
                continue
            line = line.split("\t")
            cols = len(line)
            break

    # narrowPeak has 10 columns
    # and the peak column is >= 0
    if cols != 10 or int(line[9]) < 0:
        return False

    if not check_values:
        return True

    # check if the peak values aren't all zeroes
    summit_values = 0
    sample_size = 20  # check an arbitrary number of lines
    with open(bed) as b:
        for n, line in enumerate(b):
            if line.startswith("#"):
                continue
            line = line.split("\t")
            peak_val = int(line[9])

            # value must be >=0
            if peak_val < 0:
                return False
            summit_values += peak_val
            if n >= sample_size:
                break

    if summit_values > 0:
        return True
    return False


def bed_resize(genome, bed_in, bed_out, width=200, narrowpeak=False, fix_outliers=False, output_bed3=True, verbose=True):
    """
    Set bed region width.

    If the input bed is a narrowPeak file (narrowpeak=True),
    center region on the summit (start+peak).
    Otherwise center on the middle of the region.

    If fix_outliers is set to True, shift regions to fit their chromosomes.
    Otherwise drop these regions.

    If output_bed3 is set to False, output the whole bed file.
    """
    half_seqlen = width // 2
    chrom_sizes = genomepy.Genome(genome).sizes
    missing_chrm = []

    if narrowpeak:
        def get_summit(_start, _, summit_offset):
            return _start + int(summit_offset)
        summit_col = 9
    else:
        def get_summit(_start, _end, _):
            return (_start + _end) // 2
        summit_col = 0  # unused

    with open(bed_in) as old, open(bed_out, "w") as new:
        for line in old:
            if line.startswith("#"):
                continue
            line = line.split("\t")
            chrm = str(line[0])
            if chrm not in chrom_sizes.keys():
                missing_chrm.append(chrm)
                continue
            start = int(line[1])
            end = int(line[2])
            rest = line[3:] if not output_bed3 else []

            chrm_len = chrom_sizes[chrm]
            if width == end - start:
                nstart = str(start)
                nend = str(end)
            elif chrm_len <= width:
                if not fix_outliers:
                    continue
                nstart = str(0)
                nend = str(chrm_len)
            else:
                summit = get_summit(start, end, line[summit_col])
                if not fix_outliers:
                    nstart = str(summit - half_seqlen)
                    nend = str(summit + half_seqlen)
                    if int(nstart) < 0 or int(nend) > chrm_len:
                        continue
                else:
                    # adjust the summit for the chromosome boundaries
                    summit = max(summit, 0 + half_seqlen)
                    summit = min(summit, chrm_len - half_seqlen)

                    nstart = str(summit - half_seqlen)
                    nend = str(summit + half_seqlen)

            new.write("\t".join([chrm, nstart, nend] + rest) + "\n")

    if missing_chrm and verbose:
        print(
            f"The following contigs were present in " +
            f"'{os.path.basename(bed_in)}', " +
            f"but were missing in the genome file: " +
            f"{', '.join(list(set(missing_chrm)))}\n"
        )
    return bed_out


class CombineBedFiles:
    def __init__(self, genome, peakfiles, verbose=True):
        self.genome = genome
        self.list_of_peakfiles = peakfiles if isinstance(peakfiles, list) else [peakfiles]
        self.verbose = verbose

    def run(self, outfile, width=200, force=False):
        if force or not os.path.exists(outfile):
            tmpdir = tempfile.mkdtemp()
            try:
                list_of_beds = []
                for peakfile in self.list_of_peakfiles:
                    # use narrowPeak Peak location for region centering if possible
                    is_np = is_narrowpeak(peakfile)
                    resized_peakfile = os.path.join(tmpdir, os.path.basename(peakfile))

                    # resize each BED region to 200 BP
                    bed_resize(
                        genome=self.genome,
                        bed_in=peakfile,
                        bed_out=resized_peakfile,
                        width=width,
                        narrowpeak=is_np,
                        verbose=self.verbose
                    )
                    bed_sort(resized_peakfile)
                    list_of_beds.append(resized_peakfile)

                # merge resized beds into one
                merged_bed = os.path.join(tmpdir, "merged")
                bed_merge(list_of_beds=list_of_beds, merged_bed=merged_bed)

                bed_sort(merged_bed)
                shutil.copy2(merged_bed, outfile)
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)


class CombineBamFiles:
    def __init__(self, bams):
        self.list_of_bams = bams if isinstance(bams, list) else [bams]

    def run(self, outfile, force=False):
        if force or not os.path.exists(outfile):
            tmpdir = tempfile.mkdtemp()
            try:
                # only sort & index bams if needed
                try:
                    for bam in self.list_of_bams:
                        bam_index(bam, force=False)  # assumes sorted
                    merged_bam = os.path.join(tmpdir, "merged.bam")
                    bam_merge(self.list_of_bams, merged_bam)
                except Exception:
                    # sort, index & try again
                    for bam in self.list_of_bams:
                        bam_sort(bam)
                    merged_bam = os.path.join(tmpdir, "merged.bam")
                    bam_merge(self.list_of_bams, merged_bam)

                shutil.copy2(merged_bam, outfile)
                shutil.copy2(f"{merged_bam}.bai", f"{outfile}.bai")
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)


# def bed_sum_coverages(multi_bam_coverage, sum_bam_coverage):
#     """
#     MultiBamCov returns a BED3+n with one column per bam.
#     This function sums up all bam counts and returns a BED3+1.
#     """
#     bed = pd.read_csv(multi_bam_coverage, header=None, sep="\t")
#     columns = bed.shape[1]
#     if columns != 4:
#         bed3 = bed.iloc[:, :3]
#         scores = bed.iloc[:, 3:].sum(axis=1)
#         bed = pd.concat([bed3, scores], axis=1)
#     bed.to_csv(sum_bam_coverage, sep="\t", header=False, index=False)


def normalize_peaks(bam_coverage, bed_output, dist_func="lognorm_dist", **kwargs):
    """
    Fit the bam coverage scores to a distribution
    """
    bed = pd.read_csv(bam_coverage, header=None, sep="\t")
    region = (bed[0] + ":" + bed[1].astype(str) + "-" + bed[2].astype(str))
    score = bed[3]

    # obtain a distribution
    dist_func = Distributions().set(dist_func)
    dist = dist_func(score, **kwargs)

    # replace scores with distribution values
    ascending_dist = np.sort(dist)
    ascending_scores_index = np.searchsorted(np.sort(score), score)
    norm_score = np.array([ascending_dist[i] for i in ascending_scores_index])

    logn_score = np.log(norm_score + 1)
    scaled_score = minmax_scale(logn_score)
    log10_score = np.log10(norm_score + 1)

    data = {
        "region": region,  # ex: "chr1:0-200"
        "score": score,
        "norm_score": norm_score,
        "logn_score": logn_score,
        "scaled_score": scaled_score,
        "log10_score": log10_score,  # used by the original function
    }
    bed = pd.DataFrame(data=data)
    bed.to_csv(bed_output, sep="\t", index=False)


class ScorePeaks:
    def __init__(self, bed, bam, verbose=True):
        self.bam = bam  # one sorted & indexed bam file with reads representing enhancer activity
        self.bed = bed  # one bed file with putative enhancer binding regions
        self.verbose = verbose

    def count_reads(self, coverage_file):
        tmpdir = tempfile.mkdtemp()
        try:
            bam_coverage = os.path.join(tmpdir, "bam_coverage")
            count_reads(self.bam, self.bed, bam_coverage)

            shutil.copy2(bam_coverage, coverage_file)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def run(self, outfile, dist_func="lognorm_dist", force=False, **kwargs):
        # save the results as it takes ages to run
        coverage_file = os.path.join(os.path.dirname(outfile), "raw_enhancer_coverage.bed")
        if force or not os.path.exists(coverage_file):
            if self.verbose:
                print("Running bam coverage (slow)")
            self.count_reads(coverage_file)

        # fit bam read counts to specified distribution
        normalize_peaks(coverage_file, outfile, dist_func=dist_func, **kwargs)


class ScoreMotifs:
    def __init__(self, genome, bed, pfmfile=None, ncore=1, verbose=True):
        self.genome = genome
        self.bed = bed  # one bed file with putative enhancer binding regions
        self.pfm_file = pfmfile_location(pfmfile)
        self.ncore = ncore
        self.verbose = verbose

    def setup_gimme_scanner(self):
        s = Scanner(ncpus=self.ncore)
        s.set_motifs(self.pfm_file)
        s.set_genome(self.genome)

        # generate GC background index
        _ = s.best_score([], zscore=True, gc=True)
        if self.verbose:
            print("Scanner loaded")
        return s

    def get_motif_scores(self, enhancer_regions_bed, pfmscorefile):
        """
        Scan for TF binding motifs in potential enhancer regions.
        """
        scanner = self.setup_gimme_scanner()

        with open(self.pfm_file) as f:
            motifs = read_motifs(f)

        # new file with header only (append data in chunks)
        with open(pfmscorefile, 'w') as f:
            # Quan: When we built model, rank and minmax normalization was used.
            cols = ["motif", "region", "zscore"]  # , "zscoreRank"]
            f.write("\t".join(cols)+"\n")

        seqs = [s.split(" ")[0] for s in as_fasta(enhancer_regions_bed, genome=self.genome).ids]
        with tqdm(total=len(seqs), unit="regions") as pbar:
            # Run 10k regions per scan.
            chunksize = 10_000
            for chunk in range(0, len(seqs), chunksize):
                pfm_score = []
                chunk_seqs = seqs[chunk:chunk+chunksize]
                # We are using GC-normalization for motif scanning as many enhancer binding regions are GC-enriched.
                chunk_scores = scanner.best_score(chunk_seqs, zscore=True, gc=True)
                # for each seq, store the score of each motif
                for seq, scores in zip(chunk_seqs, chunk_scores):
                    for motif, score in zip(motifs, scores):
                        pfm_score.append([motif.id, seq, score])
                    pbar.update(1)
                pfm_score = pd.DataFrame(pfm_score, columns=cols)  # ["motif", "region", "zscore"])

                # TODO: should this be a separate function (more modular but way slower)? See "normalize_motifs"
                # pfm_score["zscoreRank"] = minmax_scale(stats.rankdata(pfm_score["zscore"]))

                pfm_score[cols].to_csv(pfmscorefile, sep="\t", header=False, mode='a')

    def normalize_motifs(self, bed_input, bed_output):
        """
        Add normalized scores to the scored motifs
        """
        bed = dd.read_csv(bed_input, sep="\t")
        bed["rank_zscore"] = minmax_scale(stats.rankdata(bed["zscore"]))
        bed.to_csv(
            bed_output, sep="\t",  # to_csv args
            single_file=True, compute_kwargs={"num_workers": self.ncore}  # dask args
        )

    # def run(self, outfile, force=False):
    #     if force or not os.path.exists(outfile):
    #         tmpdir = tempfile.mkdtemp()
    #         try:
    #             if self.verbose:
    #                 print("Running gimme scan (really slow)")
    #             pfm_weight = os.path.join(tmpdir, "peak_weight")
    #             self.get_motif_scores(self.bed, pfm_weight)
    #
    #             shutil.copy2(pfm_weight, outfile)
    #         finally:
    #             shutil.rmtree(tmpdir, ignore_errors=True)

    def run(self, outfile, force=False):
        raw_motif_scores = os.path.join(os.path.dirname(outfile), "raw_motif_scores.bed")
        if force or not os.path.exists(raw_motif_scores):
            tmpdir = tempfile.mkdtemp()
            try:
                if self.verbose:
                    print("Running gimme scan (really slow)")
                tmp_motif_scores = os.path.join(tmpdir, "motif_scores")
                self.get_motif_scores(self.bed, tmp_motif_scores)

                shutil.copy2(tmp_motif_scores, raw_motif_scores)
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

        if force or not os.path.exists(outfile):
            self.normalize_motifs(raw_motif_scores, outfile)

    # def run(self, outfile, dist_func="lognorm_dist", force=False, **kwargs):
    #     # save the results as it takes ages to run
    #     coverage_file = os.path.join(os.path.dirname(outfile), "raw_enhancer_coverage.bed")
    #     if force or not os.path.exists(coverage_file):
    #         if self.verbose:
    #             print("Running bam coverage (slow)")
    #         self.count_reads(coverage_file)
    #
    #     # fit bam read counts to specified distribution
    #     normalize_peaks(coverage_file, outfile, dist_func=dist_func, **kwargs)


class Binding:
    def __init__(self, peak_weights, motif_weights, pfmfile=None, model=None, ncore=1, verbose=True, *args, **kwargs):
        self.peak_weights = peak_weights  # output from ScorePeaks
        self.motif_weights = motif_weights  # output from ScoreMotifs

        self.pfm_file = pfmfile_location(pfmfile)
        self.motifs2factors_file = self.pfm_file.replace(".pfm", ".motif2factors.txt")
        self.motifs2factors = self.filter_transcription_factors(*args, **kwargs)

        self.model = model
        if self.model is None:
            # dream_model.txt is a 2D logistic regression model.
            package_dir = os.path.dirname(__file__)
            self.model = os.path.join(package_dir, "db", "dream_model_p300.pickle")

        self.ncore = ncore
        self.verbose = verbose

    def filter_transcription_factors(self, curation_filter=None, tf_list=None, whitelist=True):
        """
        filter transcription factors from the motif database

        curation_filter: If None (default), keep all factors.
        If True, keep only curated factors. If False, keep only non-curated factors.
        Note: "Curated" TFs have direct evidence for binding or are manually selected for likely binding.

        tf_list: an optional, single-column file with (case-insensitive) transcription factor names.
        whitelist: if True (default), tf_list is used as a whitelist. If False, as a blacklist.
        """
        # note: dask dataframe (returned before computing!)
        m2f = dd.read_csv(self.motifs2factors_file, sep="\t")

        # rename stuff
        m2f.rename(columns={"Motif": "motif", "Factor": "factor", "Curated": "curated"}, inplace=True)
        m2f['factor'] = m2f.factor.str.upper()  # make case-insensitive
        m2f.replace("T", "TBXT", inplace=True)  # rename T to TBXT

        # filter by curation
        if curation_filter is True:
            m2f = m2f.loc[m2f.curated == "Y"]
        elif curation_filter is False:
            m2f = m2f.loc[m2f.curated == "N"]

        # shrink table
        m2f = m2f[["motif", "factor"]]  # subset
        m2f.drop_duplicates(inplace=True)  # case-insensitivity adds loads of duplicates (Sox9 and SOX9)

        # filter by white/blacklist
        if tf_list:
            tfs = pd.read_csv(tf_list, header=None)[0].str.upper().tolist()  # make case-insensitive
            m2f = m2f.loc[m2f.Factor.isin(tfs)] if whitelist else m2f.loc[~m2f.Factor.isin(tfs)]

        return m2f

    def get_binding_score(self, motif_weights, peak_weights, outfile):
        """
        Infer TF binding score from motif z-score and peak intensity.
        """
        # merge the scoring tables
        m = dd.read_csv(motif_weights, sep="\t")
        m = m.merge(
            dd.read_csv(peak_weights, sep="\t", blocksize=200e6),
            on="region"
        )[["motif", "region", "zscore", "log10_score"]]

        # filter scoring tables for motifs found in motifs2factors
        m = m.merge(self.motifs2factors, on="motif")  # also adds "factor" column

        # combine scores
        m = m.groupby(["factor", "region"])[["zscore", "log10_score"]].mean()
        m = m.groupby(["region"])[["zscore", "log10_score"]].mean()
        m = m.dropna().reset_index()

        with dask.diagnostics.ProgressBar():
            m = m.compute(num_workers=self.ncore)

        # Load model
        with open(self.model, "rb") as f:
            clf = pickle.load(f)
        m["binding"] = clf.predict_proba(m[["zscore", "log10_score"]])[:, 1]

        m.to_csv(outfile, sep="\t", index=False)

    def run(self, outfile, force=False):
        if force or not os.path.exists(outfile):
            self.get_binding_score(self.peak_weights, self.motif_weights, outfile)


# class ScorePeaks:
#     def __init__(self, bams, peaks):
#         self.list_of_bams = bams if isinstance(bams, list) else [bams]
#         self.peaks = peaks
#
#     def count_reads(self, coverage_file):
#         tmpdir = tempfile.mkdtemp()
#         try:
#             # merge bams
#             try:
#                 for bam in self.list_of_bams:
#                     bam_index(bam, force=False)  # assumes sorted
#                 merged_bam = os.path.join(tmpdir, "merged.bam")
#                 bam_merge(self.list_of_bams, merged_bam)
#             except Exception:
#                 # sort, index & try again
#                 for bam in self.list_of_bams:
#                     bam_sort(bam)
#                 merged_bam = os.path.join(tmpdir, "merged.bam")
#                 bam_merge(self.list_of_bams, merged_bam)
#
#             # bam read counts
#             bam_coverage = os.path.join(tmpdir, "bam_coverage")
#             count_reads(merged_bam, self.peaks, bam_coverage)
#
#             shutil.copy2(bam_coverage, coverage_file)
#
#             # for bam in self.list_of_bams:
#             #     bam_index(bam, force=False)
#             #
#             # # bam read counts per bam file
#             # multi_bam_coverage = os.path.join(tmpdir, "multi_bam_coverage")
#             # count_reads(self.list_of_bams, self.peaks, multi_bam_coverage)
#             #
#             # # sum bam read counts
#             # sum_bam_coverage = os.path.join(tmpdir, "sum_bam_coverage")
#             # sum_coverages(multi_bam_coverage, sum_bam_coverage)
#             #
#             # shutil.copy2(sum_bam_coverage, coverage_file)
#         finally:
#             shutil.rmtree(tmpdir, ignore_errors=True)
#
#     def run(self, outfile, force=False, dist_func="lognorm_dist", **kwargs):
#         # save the results as it takes ages to run
#         coverage_file = os.path.join(os.path.dirname(outfile), "raw_enhancer_coverage.bed")
#         if force or not os.path.exists(coverage_file):
#             print("running bam coverage (slow)")
#             self.count_reads(coverage_file)
#
#         # fit bam read counts to specified distribution
#         normalize(coverage_file, outfile, dist_func=dist_func, **kwargs)


# class Binding(object):
#     def __init__(self, genome, scored_peaks, model=None, pfmfile=None, ncore=1, verbose=True):
#         self.genome = genome
#         self.scored_peaks = scored_peaks
#         # self.outfile = outfile
#         self.model = model
#         self.ncore = ncore
#         self.verbose = verbose
#
#         if self.model is None:
#             # dream_model.txt is a 2D logistic regression model.
#             package_dir = os.path.dirname(__file__)
#             self.model = os.path.join(package_dir, "db", "dream_model_p300.pickle")
#
#         # Motif information file
#         self.pfmfile = pfmfile_location(pfmfile)
#         self.motifs2factors = self.pfmfile.replace(".pfm", ".motif2factors.txt")
#
#     def setup_gimme_scanner(self):
#         s = Scanner(ncpus=self.ncore)
#         s.set_motifs(self.pfmfile)
#         s.set_genome(self.genome)
#         # s.set_threshold(threshold=0.0)
#
#         # generate GC background index
#         _ = s.best_score([], zscore=True, gc=True)
#         if self.verbose:
#             print("Scanner loaded")
#         return s
#
#     def get_motif_scores(self, enhancer_regions_bed, pfmscorefile):
#         """
#         Scan for TF binding motifs in potential enhancer regions.
#         """
#         scanner = self.setup_gimme_scanner()
#         # scanner = Scanner(ncpus=self.ncore)
#         # scanner.set_motifs(self.pfmfile)
#         # scanner.set_genome(self.genome)
#
#         with open(self.pfmfile) as f:
#             motifs = read_motifs(f)
#
#         # new file with header only (append data in chunks)
#         with open(pfmscorefile, 'w') as f:
#             # Quan: When we built model, rank and minmax normalization was used.
#             cols = ["enhancer", "zscore", "zscoreRank"]
#             f.write("\t".join(cols)+"\n")
#
#         seqs = [s.split(" ")[0] for s in as_fasta(enhancer_regions_bed, genome=self.genome).ids]
#         with tqdm(total=len(seqs), unit="seq") as pbar:
#             # Run 10k regions per scan.
#             chunksize = 10000
#             for chunk in range(0, len(seqs), chunksize):
#                 pfm_score = []
#                 chunk_seqs = seqs[chunk:chunk+chunksize]
#                 # We are using GC-normalization for motif scanning as many enhancer binding regions are GC-enriched.
#                 chunk_scores = scanner.best_score(chunk_seqs, zscore=True, gc=True)
#                 for seq, scores in zip(chunk_seqs, chunk_scores):
#                     for motif, score in zip(motifs, scores):
#                         pfm_score.append([motif.id, seq, score])
#                     pbar.update(1)
#                 pfm_score = pd.DataFrame(pfm_score, columns=["motif", "enhancer", "zscore"])
#                 pfm_score = pfm_score.set_index("motif")
#                 pfm_score["zscoreRank"] = minmax_scale(stats.rankdata(pfm_score["zscore"]))
#
#                 pfm_score[cols].to_csv(pfmscorefile, sep="\t", header=False, mode='a')
#
#     def get_binding_score(self, pfm, peak, outfile):
#         """
#         Infer TF binding score from motif z-score and peak intensity.
#         Arguments:
#             pfm {[type]} -- [motif scan result]
#             peak {[type]} -- [peak intensity]
#         Returns:
#             [type] -- [the predicted tf binding table]
#         """
#         peak = dd.read_csv(peak, sep="\t", blocksize=200e6)
#         pfm = dd.read_csv(pfm, sep="\t")
#
#         # Load model
#         with open(self.model, "rb") as f:
#             clf = pickle.load(f)
#
#         # ft = self.filtermotifs2factors
#
#         r = pfm.merge(peak, left_on="enhancer", right_on="peak")[
#             ["motif", "enhancer", "zscore", "log10_peakRPKM"]
#         ]
#         # r = r.merge(ft, left_on="motif", right_on="Motif")
#         r = r.groupby(["factor", "enhancer"])[["zscore", "log10_peakRPKM"]].mean()
#         r = r.dropna().reset_index()
#
#         with dask.diagnostics.ProgressBar():
#             table = r.compute(num_workers=self.ncore)
#         table["binding"] = clf.predict_proba(table[["zscore", "log10_peakRPKM"]])[:, 1]
#
#         table.to_csv(outfile, sep="\t", index=False)
#
#     def run(self, outfile):
#         tmpdir = tempfile.mkdtemp()
#         try:
#             print("running gimme scan (really slow)")
#             pfm_weight = os.path.join(tmpdir, "peak_weight")
#             self.get_motif_scores(self.scored_peaks, pfm_weight)
#
#             print("running classifier (slow)")
#             peak_weight = self.scored_peaks
#             table = os.path.join(tmpdir, "table")
#             self.get_binding_score(pfm_weight, peak_weight, table)
#
#             shutil.copy2(table, outfile)
#         finally:
#             shutil.rmtree(tmpdir, ignore_errors=True)
