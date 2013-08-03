# Licensed under a 3-clause BSD style license - see LICENSE.rst
from __future__ import print_function

from ..query import BaseQuery
from ..utils.class_or_instance import class_or_instance
from ..utils import commons
import os
import astropy.units as u
import astropy.coordinates as coord
import astropy.utils.data as aud
import warnings
import json
from collections import defaultdict
import traceback
import tempfile
# maintain compat with PY<2.7
from astropy.utils import OrderedDict
import astropy.io.votable as votable
from . import VIZIER_SERVER, VIZIER_TIMEOUT, ROW_LIMIT

__all__ = ['Vizier']


class Vizier(BaseQuery):
    TIMEOUT = VIZIER_TIMEOUT
    VIZIER_SERVER = VIZIER_SERVER
    ROW_LIMIT = ROW_LIMIT

    def __init__(self, columns=None, column_filters=None, keywords=None):
        self._columns = None
        self._column_filters = None
        self._keywords = None
        if keywords:
            self.keywords = keywords
        if columns:
            self.columns = columns
        if column_filters:
            self.column_filters = column_filters

    @class_or_instance
    def _server_to_url(self, return_type='votable'):
        """
        Not generally meant to be modified, but there are different valid
        return types supported by Vizier, listed here:
        http://vizier.u-strasbg.fr/doc/asu-summary.htx

        HTML: VizieR
        votable: votable
        tab-separated-values: asu-tsv
        FITS ascii table: asu-fits
        FITS binary table: asu-binfits
        plain text: asu-txt
        """
        return "http://" + Vizier.VIZIER_SERVER() + "/viz-bin/" + return_type

    @property
    def keywords(self):
        """The set of keywords to filter the Vizier search"""
        return self._keywords

    @keywords.setter
    def keywords(self, value):
        self._keywords = VizierKeyword(value)

    @keywords.deleter
    def keywords(self):
        self._keywords = None

    @property
    def columns(self):
        """The columns that must be returned in the output"""
        return self._columns

    @columns.setter
    def columns(self, value):
        if isinstance(value, basestring):
            value = list(value)
        if not isinstance(value, list):
            raise TypeError(
                "Column(s) should be specified as a list or string")
        self._columns = value

    @columns.deleter
    def columns(self):
        if self.column_filters is not None:
            raise Exception(
                "One or more column_filter(s) exist. Aborting delete.")
        self._columns = None

    @property
    def column_filters(self):
        """Set constraints on one or more columns of the output"""
        return self._column_filters

    @column_filters.setter
    def column_filters(self, value_dict):
        # give warning if filtered column not in self.columns
        # Vizer will return these columns in the output even if are not set in
        # self.columns
        if self.columns is None:
            raise Exception(
                "Columns must be set before specifiying column_filters.")
        elif 'all' not in self.columns:
            for val in set(value_dict.keys()) - set(self.columns):
                warnings.warn(
                    "{val}: to be filtered but not set as an output column".format(val=val))
                raise Exception(
                    "Column-Filters not a subset of the output columns")
        self._column_filters = value_dict

    @column_filters.deleter
    def column_filters(self):
        self._column_filters = None

    @class_or_instance
    def find_catalogs(self, keywords, verbose=False):
        """
        Search Vizier for catalogs based on a set of keywords, e.g. author name

        Parameters
        ----------
        keywords : list or string
            List of keywords, or space-separated set of keywords.
            From `Vizier <http://vizier.u-strasbg.fr/doc/asu-summary.htx>`_:
            "names or words of title of catalog. The words are and'ed, i.e.
            only the catalogues characterized by all the words are selected."

        Returns
        -------
        Dictionary of the "Resource" name and the VOTable resource object.
        "Resources" are generally publications; one publication may contain
        many tables.

        Example
        -------
        >>> from astroquery.vizier import Vizier
        >>> catalog_list = Vizier.find_catalogs('Kang W51')
        >>> print catalog_list
        {u'J/ApJ/706/83': <astropy.io.votable.tree.Resource at 0x108d4d490>,
         u'J/ApJS/191/232': <astropy.io.votable.tree.Resource at 0x108d50490>}
        >>> print {k:v.description for k,v in catalog_list.iteritems()}
        {u'J/ApJ/706/83': u'Embedded YSO candidates in W51 (Kang+, 2009)',
         u'J/ApJS/191/232': u'CO survey of W51 molecular cloud (Bieging+, 2010)'}
        """

        if isinstance(keywords, list):
            keywords = " ".join(keywords)

        data_payload = {'-words':keywords, '-meta.all':1}
        response = commons.send_request(
            self._server_to_url(),
            data_payload,
            Vizier.TIMEOUT())
        result = self._parse_result(response, verbose=verbose, get_catalog_names=True)

        return result

    @class_or_instance
    def get_catalogs(self, catalog, verbose=False):
        """
        Query the Vizier service for a specific catalog

        Parameters
        ----------
        catalog : str or list, optional
            The catalog(s) that will be retrieved

        Returns
        -------
        result : `~astroquery.utils.common.TableList`
            The results in a list of `astropy.table.Table`.
        """
        response = self.get_catalogs_async(catalog=catalog)
        result = self._parse_result(response, verbose=verbose)
        return result

    @class_or_instance
    def get_catalogs_async(self, catalog, verbose=False):
        """
        Asynchronous version of get_catalog
        """

        data_payload = self._args_to_payload(catalog=catalog,
                                             caller='get_catalog_async')
        response = commons.send_request(
            self._server_to_url(),
            data_payload,
            Vizier.TIMEOUT())
        return response

    # This doesn't work:
    # TypeError: unsupported operand type(s) for +=: 'NoneType' and 'NoneType'
    # the decorator breaks this approach.  Perhaps we can pass the docstring to
    # the decorator?
    # get_catalog_async.__doc__ += get_catalog.__doc__

    @class_or_instance
    def query_object(self, object_name, catalog=None, verbose=False):
        """
        Query the Vizier service for a known identifier and return the
        results as an `astropy.table.Table`.

        Parameters
        ----------
        object_name : str
            The name of the identifier.
        catalog : str or list, optional
            The catalog(s) which must be searched for this identifier.
            If not specified, all matching catalogs will be searched.

        Returns
        -------
        result : `~astroquery.utils.common.TableList`
            The results in a list of `astropy.table.Table`.
        """
        response = self.query_object_async(object_name, catalog=catalog)
        result = self._parse_result(response, verbose=verbose)
        return result

    @class_or_instance
    def query_object_async(self, object_name, catalog=None):
        """
        Serves the same purpose as `astroquery.vizier.Vizier.query_object` but only
        returns the HTTP response rather than the parsed result.

        Parameters
        ----------
        object_name : str
            The name of the identifier.
        catalog : str or list, optional
            The catalog(s) which must be searched for this identifier.
            If not specified, all matching catalogs will be searched.

        Returns
        -------
        response : `requests.Response` object
            The response of the HTTP request.

        """
        data_payload = self._args_to_payload(
            object_name,
            catalog=catalog,
            caller='query_object_async')
        response = commons.send_request(
            self._server_to_url(),
            data_payload,
            Vizier.TIMEOUT())
        return response

    @class_or_instance
    def query_region(self, coordinates, radius=None,
                     width=None, height=None, catalog=None, verbose=False):
        """
        Returns the results from a Vizier service on querying a region around
        a known identifier or coordinates. Region around the target may be specified
        by a radius or box.

        Parameters
        ----------
        coordinates : str or `astropy.coordinates` object
            The target around which to search. It may be specified as a string
            in which case it is resolved using online services or as the appropriate
            `astropy.coordinates` object. ICRS coordinates may also be entered
            as a string.
        radius : str or `astropy.units.Quantity` object
            The string must be parsable by `astropy.coordinates.Angle`. The appropriate
            `Quantity` object from `astropy.units` may also be used.
        width : str or `astropy.units.Quantity` object.
            Must be specified for a box region. Has the same format
            as radius above.
        height : str or `astropy.units.Quantity` object.
            Must be specified with the width for a box region that is a rectangle.
            Has the same format as radius above.
        catalog : str or list, optional
            The catalog(s) which must be searched for this identifier.
            If not specified, all matching catalogs will be searched.

        Returns
        -------
        result : `~astroquery.utils.common.TableList`
            The results in a list of `astropy.table.Table`.
        """
        response = self.query_region_async(
            coordinates, radius=radius, height=height,
            width=width, catalog=catalog)
        result = self._parse_result(response, verbose=verbose)
        return result

    @class_or_instance
    def query_region_async(
            self, coordinates, radius=None, height=None, width=None, catalog=None):
        """
        Serves the same purpose as `astroquery.vizier.Vizier.query_region` but only
        returns the HTTP response rather than the parsed result.

        Parameters
        ----------
        coordinates : str or `astropy.coordinates` object
            The target around which to search. It may be specified as a string
            in which case it is resolved using online services or as the appropriate
            `astropy.coordinates` object. ICRS coordinates may also be entered as
            a string.
        radius : str or `astropy.units.Quantity` object
            The string must be parsable by `astropy.coordinates.Angle`. The appropriate
            `Quantity` object from `astropy.units` may also be used.
        width : str or `astropy.units.Quantity` object.
            Must be specified for a box region. Has the same format
            as radius above.
        height : str or `astropy.units.Quantity` object.
            Must be specified with the width for a box region that is a rectangle.
            Has the same format as radius above.
        catalog : str or list, optional
            The catalog(s) which must be searched for this identifier.
            If not specified, all matching catalogs will be searched.

        Returns
        -------
        response : `requests.Response` object
            The response of the HTTP request.

        """
        data_payload = self._args_to_payload(
            coordinates, radius=radius, height=height,
            width=width, catalog=catalog, caller='query_region_async')
        response = commons.send_request(
            self._server_to_url(),
            data_payload,
            Vizier.TIMEOUT())
        return response

    @class_or_instance
    def _args_to_payload(self, *args, **kwargs):
        """
        accepts the arguments for different query functions and
        builds a script suitable for the Vizier votable CGI.
        """
        body = OrderedDict()
        caller = kwargs['caller']
        del kwargs['caller']
        catalog = kwargs.get('catalog')
        if catalog is not None:
            if isinstance(catalog, basestring):
                body['-source'] = catalog
            elif isinstance(catalog, list):
                body['-source'] = ",".join(catalog)
            else:
                raise TypeError("Catalog must be specified as list or string")
        if caller == 'query_object_async':
            body["-c"] = args[0]
        elif caller == 'query_region_async':
            c = commons.parse_coordinates(args[0])
            ra = str(c.icrs.ra.degree)
            dec = str(c.icrs.dec.degree)
            if dec[0] not in ['+', '-']:
                dec = '+' + dec
            body["-c"] = "".join([ra, dec])
            # decide whether box or radius
            if kwargs.get('radius') is not None:
                radius = kwargs['radius']
                unit, value = _parse_dimension(radius)
                switch = "-c.r" + unit
                body[switch] = value
            elif kwargs.get('width') is not None:
                width = kwargs['width']
                w_unit, w_value = _parse_dimension(width)
                switch = "-c.b" + w_unit
                height = kwargs.get('height')
                # is box a rectangle or square?
                if height is not None:
                    h_unit, h_value = _parse_dimension(height)
                    if h_unit != w_unit:
                        warnings.warn(
                            "Converting height to same unit as width")
                        h_value = u.Quantity(h_value, u.Unit
                                             (_str_to_unit(h_unit))).to(u.Unit(_str_to_unit(w_unit)))
                    body[switch] = "x".join([str(w_value), str(h_value)])
                else:
                    body[switch] = "x".join([str(w_value)] * 2)
            elif kwargs.get('height'):
                warnings.warn(
                    "No width given - shape interpreted as square (height x height)")
                height = kwargs['height']
                h_unit, h_value = _parse_dimension(height)
                switch = "-c.b" + h_unit
                body[switch] = h_value
            else:
                raise Exception(
                    "At least one of radius, width/height must be specified")
        # set output parameters
        if not isinstance(self.columns, property) and self.columns is not None:
            if "all" in self.columns:
                body["-out"] = "**"
            else:
                out_cols = ",".join([col for col in self.columns])
                # if default then return default cols and listed cols
                if "default" in self.columns:
                    body["-out.add"] = out_cols
                # else return only the listed cols
                else:
                    body["-out"] = out_cols
        # otherwise ask to return default columns
        else:
            body["-out"] = "*"
        # set the maximum rows returned
        body["-out.max"] = Vizier.ROW_LIMIT()
        script = "\n".join(["{key}={val}".format(key=key, val=val)
                           for key, val in body.items()])
        # add keywords
        if not isinstance(self.keywords, property) and self.keywords is not None:
            script += str(self.keywords)
        # add column filters
        if not isinstance(self.column_filters, property) and self.column_filters is not None:
            filter_str = "\n".join(["{key}={constraint}".format(key=key, constraint=constraint) for key, constraint in
                                    self.column_filters.items()])
            script += "\n" + filter_str
        return script

    @class_or_instance
    def _parse_result(self, response, get_catalog_names=False, verbose=False):
        """
        Parses the HTTP response to create an `astropy.table.Table`.
        Returns the raw result as a string in case of parse errors.

        Parameters
        ----------
        response : `requests.Response`
            The response of the HTTP POST request
        get_catalog_names : bool
            If specified, return only the table names (useful for table
            discovery)

        Returns
        -------
        `astroquery.utils.commons.TableList`
            An OrderedDict of `astropy.table.Table` objects.
            If there are errors in the parsing, then returns the raw results as a string.
        """
        if not verbose:
            commons.suppress_vo_warnings()
        try:
            tf = tempfile.NamedTemporaryFile()
            tf.write(response.content.encode('utf-8'))
            tf.file.flush()
            vo_tree = votable.parse(tf.name, pedantic=False)
            if get_catalog_names:
                return dict([(R.name,R) for R in vo_tree.resources])
            else:
                table_list = [(t.name, t.to_table())
                              for t in vo_tree.iter_tables() if len(t.array) > 0]
                return commons.TableList(table_list)

        except:
            traceback.print_exc()  # temporary for debugging
            warnings.warn(
                "Error in parsing result, returning raw result instead")
            return response.content


def _parse_dimension(dim):
    """
    Retuns the Vizier-formatted units and values for box/radius
    dimensions in case of region queries.

    Parameters
    ----------
    dim : `astropy.units.Quantity` or `astropy.coordinates.Angle`

    Returns
    -------
    (unit, value) : tuple
        formatted for Vizier.
    """
    if isinstance(dim, u.Quantity) and dim.unit in u.deg.find_equivalent_units():
        if dim.unit == u.arcsec:
            unit, value = 's', dim.value
        elif dim.unit == u.arcmin:
            unit, value = 'm', dim.value
        else:
            unit, value = 'd', dim.to(u.deg).value
    # otherwise must be an Angle or be specified in hours...
    else:
        try:
            new_dim = commons.radius_to_degrees(dim)
            unit, value = 'd', new_dim
        except (u.UnitsException, coord.errors.UnitsError, AttributeError):
            raise u.UnitsException("Dimension not in proper units")

    return unit, value


def _str_to_unit(string):
    """
    translates to the string representation of the `astropy.units`
    quantity from the Vizier format for the unit.

    Parameters
    ----------
    string : str
        `s`, `m` or `d`

    Returns
    -------
    string equivalent of the corresponding `astropy` unit.
    """
    str_to_unit = {
        's': 'arcsec',
        'm': 'arcmin',
        'd': 'degree'
    }
    return str_to_unit[string]


class VizierKeyword(list):

    """Helper class for setting keywords for Vizier queries"""

    def __init__(self, keywords):
        file_name = aud.get_pkg_data_filename(
            os.path.join("data", "inverse_dict.json"))
        with open(file_name, 'r') as f:
            self.keyword_dict = json.load(f)
        self._keywords = None
        self.keywords = keywords

    @property
    def keywords(self):
        """ list or string for keyword(s) that must be set for the Vizier object."""
        return self._keywords

    @keywords.setter
    def keywords(self, values):
        if isinstance(values, basestring):
            values = list(values)
        keys = [key.lower() for key in self.keyword_dict]
        values = [val.lower() for val in values]
        # warn about unknown keywords
        for val in set(values) - set(keys):
            warnings.warn("{val} : No such keyword".format(val=val))
        valid_keys = [
            key for key in self.keyword_dict if key.lower() in values]
        # create a dict for each type of keyword
        set_keywords = defaultdict(list)
        for key in valid_keys:
            set_keywords[self.keyword_dict[key]].append(key)
        self._keywords = set_keywords

    @keywords.deleter
    def keywords(self):
        del self._keywords

    def __repr__(self):
        return "\n".join([self.get_keyword_str(key) for key in self.keywords])

    def get_keyword_str(self, key):
        """
        Helper function that returns the keywords, grouped into appropriate
        categories and suitable for the Vizier votable CGI.
        """
        s = ",".join([val for val in self.keywords[key]])
        keyword_name = "-kw." + key
        return keyword_name + "=" + s
