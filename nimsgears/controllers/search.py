# @author:  Reno Bowen
#           Gunnar Schaefer

from tg import expose, request
import json

import re
import datetime
import sys
import nimsdata
import numpy

from nimsgears.model import *
from nimsgears.controllers.nims import NimsController

def is_ascii(s):
    if bool(re.match(r'^[a-zA-Z0-9-_<>\s\%]+$', s)):
        return True
    else:
        return False

def is_a_number(n):
    try:
        int(n)
        return True
    except ValueError:
        return False

def is_date(s):
    if bool(re.compile(r'\s*\d+\d+').match(s)):
        return True
    else:
        return False

def is_other_field(n):
    return True

def is_age(n):
    try:
        value = int(n)
        return value >= 0
    except:
        # Not a number
        return False


validation_functions = {
    'subject_last_name' : is_ascii,
    'subject_name' : is_ascii,
    'search_exam' : is_a_number,
    'search_operator' : is_ascii,
    'search_age_min': is_age,
    'search_age_max' : is_age,
    'search_psdName' : is_ascii,
    'search_typescan': is_other_field,
    'date_from': is_date,
    'date_to': is_date,
}

def query_psdname( db_query, query_value ):
    return db_query.filter(Epoch.psd.ilike( query_value ))

def query_scantype( db_query, query_value ):
    return db_query.filter(Epoch.scan_type.ilike( query_value ))

def query_subjectname( db_query, query_value ):
    return db_query.filter(Subject.lastname.ilike( query_value ) | Subject.firstname.ilike( query_value ))

def query_exam( db_query, query_value ):
    return db_query.filter(Session.exam == int( query_value ))

def query_operator( db_query, query_value ):
    user = User.get_by(uid = query_value)
    return db_query.filter(Session.operator == user)
                    # .filter(User.uid.ilike(query_value) | User.firstname.ilike( query_value ) | User.lastname.ilike( query_value )))

def query_date_from( db_query, query_value ):
    return db_query.filter(Session.timestamp >= query_value)

def query_date_to( db_query, query_value ):
    return db_query.filter(Session.timestamp <= query_value)

def query_age_min( db_query, query_value ):
    return (db_query
            .filter(Session.timestamp - Subject.dob >= datetime.timedelta(days=float(query_value)*365.25)))

def query_age_max( db_query, query_value ):
    # We add 1 year to the age max to get the whole year interval
    max_age = 1 + int(query_value)
    return (db_query
            .filter(Session.timestamp - Subject.dob <= datetime.timedelta(days=max_age*365.25)))

query_functions = {
    'subject_name' : query_subjectname,
    'subject_last_name' : query_subjectname,
    'search_exam' : query_exam,
    'search_operator' : query_operator,
    'search_age_min' : query_age_min,
    'search_age_max' : query_age_max,
    'search_psdName' : query_psdname,
    'search_typescan': query_scantype,
    'date_from': query_date_from,
    'date_to': query_date_to,
}


class SearchController(NimsController):

    @expose('nimsgears.templates.search')
    def index(self):
        user = request.identity['user'] if request.identity else User.get_by(uid=u'@public')
        dataset_cnt = Session.query.count()
        flag = user.is_superuser
        userdataset_cnt = user.dataset_cnt
        epoch_columns = [ ('Group', 'col_sunet'), ('Experiment', 'col_exp'), ('Date & Time', 'col_datetime'), ('Scan Type', 'col_typescan'), ('Description', 'col_desc')]
        dataset_columns = [('Data Type', 'col_type')]
        scantype_values = [''] + sorted(nimsdata.nimsimage.scan_types.all)
        psd_names_tuples = DBSession.query(Epoch.psd).distinct(Epoch.psd)
        psd_values = [''] + sorted([elem[0] for elem in psd_names_tuples])
        return dict(page='search',
            psd_values=psd_values,
            userdataset_cnt=userdataset_cnt,
            flag=flag,
                dataset_cnt=dataset_cnt,
            epoch_columns=epoch_columns,
            dataset_columns=dataset_columns,
            scantype_values=scantype_values)



    @expose()
    def query(self, **kwargs):
        # For more robust search query parsing, check out pyparsing.
        print kwargs
        result = {'success': False}
        if 'search_age_min' in kwargs and'search_age_max' in kwargs and 'search_exam' in kwargs and 'search_typescan' in kwargs \
            and 'search_operator' in kwargs and 'search_psdName' in kwargs and 'date_from' in kwargs \
            and 'date_to' in kwargs and 'subject_name' in kwargs and 'subject_last_name' in kwargs:
            search_query = kwargs.values()
            search_param = kwargs.keys()
        elif 'search_age_min' in kwargs and 'search_age_max' in kwargs and 'search_exam' in kwargs and 'search_typescan' in kwargs \
            and 'search_operator' in kwargs and 'search_psdName' in kwargs and 'date_from' in kwargs \
            and 'date_to' in kwargs and 'search_all' in kwargs:
            search_query = kwargs.values()
            search_param = kwargs.keys()
        else:
            return json.dumps(result)

        search_query = [x.replace('*','%') for x in search_query]

        #Zip fields and if any field is empty remove it from parameters
        parameters = [(x,y) for x,y in zip(search_param, search_query) if y]
        parameters = [(x,y) for x,y in parameters if x != 'search_all']

        user = request.identity['user'] if request.identity else User.get_by(uid=u'@public')

        if 'search_all' in kwargs:
            db_query = (DBSession.query(Epoch, Session, Subject, Experiment)
                        .join(Session, Epoch.session)
                        .join(Subject, Session.subject)
                        .join(Experiment, Subject.experiment))
        else:
            db_query = (DBSession.query(Epoch, Session, Subject, Experiment)
                        .join(Session, Epoch.session)
                        .join(Subject, Session.subject)
                        .join(Experiment, Subject.experiment)
                        .join(Access,Experiment.accesses)
                        .filter(Access.user == user))
            for elem in parameters:
                if 'subject_name' in elem[0] or 'subject_last_name' in elem[0]:
                    db_query = db_query.filter(Access.privilege >= AccessPrivilege.value(u'Read-Only'))
                else:
                    db_query = db_query.filter(Access.privilege >= AccessPrivilege.value(u'Anon-Read'))

        if len(parameters)==0 and kwargs['date_from']=='' and kwargs['date_to']=='':
            return json.dumps(result)


        for param, query in parameters:
            if not validation_functions[param](query):
                # The query value is not valid
                result = {'success': False, 'error_message' : 'Field ' + query + 'could not be processed'}
                return json.dumps(result)
            db_query = query_functions[param](db_query, query)

        result['data'], result['attrs'] = self._process_result(db_query.all())
        result['success'] = True
        return json.dumps(result)

    def _process_result(self, db_result):
        data_list = []
        attr_list = []
        for value in db_result:
            exp = value.Experiment
            sess = value.Session
            subject = value.Subject
            epoch = value.Epoch
            data_list.append((exp.owner.gid,
                              exp.name,
                              sess.timestamp.strftime('%Y-%m-%d %H:%M'),
                              epoch.scan_type,
                              epoch.description))
            attr_list.append({'id':'epoch=%d' % epoch.id})
        return data_list, attr_list
