## Prepare data

### Genome
When you need run `ANANSE` in your sample, genome file is necessary. We recommand you download your genome file with [genomepy](https://github.com/vanheeringen-lab/genomepy), which is a python package could install genome easily.

In ANANSE, for each genome, we need:
* A genome fasta file
* A 12 columns BED file with genome annotation. 

When you would like to insall the genome with `genomepy`, you could fellow this commands, which will download both `fasta` file and `bed` file.
```
conda create -n genomepy python=3
conda activate genomepy
conda install genomepy=0.7.2

conda activate genompy

# install hg38 genome
genomepy install GRCh38 NCBI -a
```

### Motif database
By default ANANSE uses a non-redundant, clustered database of known vertebrate motifs: `gimme.vertebrate.v5.0`. These motifs come from CIS-BP (http://cisbp.ccbr.utoronto.ca/) and other sources. Large-scale benchmarks using ChIP-seq peaks show that this database shows good performance and should be a good default choice. 

If you would like to use your own motif database, please makesure your database include following two files:  
* Motif file  

    ```
    #GM.5.0.Sox.0001	M1911_1.02;;M3916_1.02;;M5846_1.02;;M6471_1.02;;M6478_1.02;;MA0084.1_SRY;;MA1152.1_SOX15;;SOX12;;SOX12_1 Sox12_bulyk_sc09-primary;;SOX15_1 Sox15_bulyk_sc09-primary;;SOX18_1 Sox18_bulyk_sc09-primary;;SOX30;;SOX30_1 Sox30_bulyk_sc09-primary;;SOX7_1 Sox7_bulyk_sc09-primary;;SOX9_1 SOX9_transfac_M00410;;SOX9_3 SOX9_jolma_DBD_M136;;SRY;;SRY_3 SRY_jaspar_MA0084.1
    >GM.5.0.Sox.0001
    0.7213	0.0793	0.1103	0.0891
    0.9259	0.0072	0.0062	0.0607
    0.0048	0.9203	0.0077	0.0672
    0.9859	0.0030	0.0030	0.0081
    0.9778	0.0043	0.0128	0.0051
    0.1484	0.0050	0.0168	0.8299
    #GM.5.0.Homeodomain.0001	M4064_1.02;;TGIF1;;TGIF1_1 TGIF_transfac_M00418;;TGIF1_HUMAN.H11MO.0.A
    >GM.5.0.Homeodomain.0001
    0.8870	0.0000	0.0178	0.0951
    0.1156	0.2033	0.6629	0.0181
    0.0017	0.7452	0.0809	0.1722
    0.0011	0.0003	0.0003	0.9983
    0.0026	0.0141	0.9721	0.0111
    0.0000	0.0189	0.0054	0.9758
    0.0006	0.9983	0.0006	0.0006
    0.9170	0.0140	0.0046	0.0644
    0.2228	0.2421	0.3300	0.2051
    0.3621	0.1054	0.2208	0.3116
    0.5727	0.0104	0.1741	0.2428
    ```

* Motif2factors file  

    ```
    Motif	Factor	Evidence	Curated
    GM.5.0.Sox.0001	SRY	JASPAR	Y
    GM.5.0.Sox.0001	SOX9	Transfac	Y
    GM.5.0.Sox.0001	Sox9	Transfac	N
    GM.5.0.Sox.0001	SOX9	SELEX	Y
    GM.5.0.Sox.0001	Sox9	SELEX	N
    ```

The `motif` file should end with `.pfm`,  and `motif2factors` file should have the same name with `motif` file and end with `motif2factors.txt`.
The defaule `gimme.vertebrate.v5.0` file can be found here: [gimme.vertebrate.v5.0.pfm](https://github.com/vanheeringen-lab/gimmemotifs/blob/master/data/motif_databases/gimme.vertebrate.v5.0.pfm) and [gimme.vertebrate.v5.0.motif2factors.txt](https://github.com/vanheeringen-lab/gimmemotifs/blob/master/data/motif_databases/gimme.vertebrate.v5.0.motif2factors.txt).
