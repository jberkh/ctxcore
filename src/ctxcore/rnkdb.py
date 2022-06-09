# -*- coding: utf-8 -*-

import os
from abc import ABCMeta, abstractmethod
from typing import Set, Tuple, Type

import pandas as pd
import pyarrow as pa
from ctdb import CisTargetDatabase
from cytoolz import memoize
from datatypes import RegionOrGeneIDs

from .genesig import GeneSignature


class PyArrowThreads:
    """
    A static class to control how many threads PyArrow is allowed to use to convert a Feather database to a pandas
    dataframe.

    By default the number of threads is set to 4.
    Overriding the number of threads is possible by using the environment variable "PYARROW_THREADS=nbr_threads".
    """

    pyarrow_threads = 4

    if os.environ.get("PYARROW_THREADS"):
        try:
            # If "PYARROW_THREADS" is set, check if it is a number.
            pyarrow_threads = int(os.environ.get("PYARROW_THREADS"))
        except ValueError:
            pass

        if pyarrow_threads < 1:
            # Set the number of PyArrow threads to 1 if a negative number or zero was specified.
            pyarrow_threads = 1

    @staticmethod
    def set_nbr_pyarrow_threads(nbr_threads=None):
        # Set number of threads to use for PyArrow when converting Feather database to pandas dataframe.
        pa.set_cpu_count(nbr_threads if nbr_threads else PyArrowThreads.pyarrow_threads)


PyArrowThreads.set_nbr_pyarrow_threads()


class RankingDatabase(metaclass=ABCMeta):
    """
    A class of a database of whole genome rankings. The whole genome is ranked for regulatory features of interest, e.g.
    motifs for a transcription factor.

    The rankings of the genes are 0-based.
    """

    def __init__(self, name: str):
        """
        Create a new instance.

        :param name: The name of the database.
        """
        assert name, "Name must be specified."

        self._name = name

    @property
    def name(self) -> str:
        """
        The name of this database of rankings.
        """
        return self._name

    @property
    @abstractmethod
    def total_genes(self) -> int:
        """
        The total number of genes ranked.
        """
        pass

    @property
    @abstractmethod
    def genes(self) -> Tuple[str]:
        """
        List of genes ranked according to the regulatory features in this database.
        """
        pass

    @property
    @memoize
    def geneset(self) -> Set[str]:
        """
        Set of genes ranked according to the regulatory features in this database.
        """
        return set(self.genes)

    @abstractmethod
    def load_full(self) -> pd.DataFrame:
        """
        Load the whole database into memory.

        :return: a dataframe.
        """
        pass

    @abstractmethod
    def load(self, gs: Type[GeneSignature]) -> pd.DataFrame:
        """
        Load the ranking of the genes in the supplied signature for all features in this database.

        :param gs: The gene signature.
        :return: a dataframe.
        """
        pass

    def __str__(self):
        """
        Returns a readable string representation.
        """
        return self.name

    def __repr__(self):
        """
        Returns a unambiguous string representation.
        """
        return "{}(name=\"{}\")".format(self.__class__.__name__, self._name)


class FeatherRankingDatabase(RankingDatabase):
    def __init__(self, fname: str, name: str):
        """
        Create a new feather database.

        :param fname: The filename of the database.
        :param name: The name of the database.
        """
        super().__init__(name=name)

        assert os.path.isfile(fname), "Database {0:s} doesn't exist.".format(fname)

        # FeatherReader cannot be pickle (important for dask framework) so filename is field instead.
        self._fname = fname
        self.ct_db = CisTargetDatabase.init_ct_db(
            ct_db_filename=self._fname,
            engine="pyarrow"
        )

    @property
    @memoize
    def total_genes(self) -> int:
        return self.ct_db.nbr_total_region_or_gene_ids

    @property
    @memoize
    def genes(self) -> Tuple[str]:
        return self.ct_db.all_region_or_gene_ids.ids

    def load_full(self) -> pd.DataFrame:
        return self.ct_db.subset_to_pandas(region_or_gene_ids=self.ct_db.all_region_or_gene_ids)

    def load(self, gs: Type[GeneSignature]) -> pd.DataFrame:
        # For some genes in the signature there might not be a rank available in the database.
        gene_set = self.geneset.intersection(set(gs.genes))

        return self.ct_db.subset_to_pandas(
            region_or_gene_ids=RegionOrGeneIDs(
                region_or_gene_ids=gene_set,
                regions_or_genes_type=self.ct_db.all_region_or_gene_ids.type
            )
        )


class MemoryDecorator(RankingDatabase):
    """
    A decorator for a ranking database which loads the entire database in memory.
    """

    def __init__(self, db: Type[RankingDatabase]):
        assert db, "Database should be supplied."
        self._db = db
        self._df = db.load_full()
        super().__init__(db.name)

    @property
    def total_genes(self) -> int:
        return self._db.total_genes

    @property
    def genes(self) -> Tuple[str]:
        return self._db.genes

    def load_full(self) -> pd.DataFrame:
        return self._df

    def load(self, gs: Type[GeneSignature]) -> pd.DataFrame:
        return self._df.loc[:, self._df.columns.isin(gs.genes)]


def opendb(fname: str, name: str) -> Type['RankingDatabase']:
    """
    Open a ranking database.

    :param fname: The filename of the database.
    :param name: The name of the database.
    :return: A ranking database.
    """
    assert os.path.isfile(fname), "{} does not exist.".format(fname)
    assert name, "A database should be given a proper name."

    extension = os.path.splitext(fname)[1]
    if extension == ".feather":
        # noinspection PyTypeChecker
        return FeatherRankingDatabase(fname, name=name)
    else:
        raise ValueError("{} is an unknown extension.".format(extension))
