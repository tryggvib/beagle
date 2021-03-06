# -*- coding: utf-8 -*-
# beagle - scrape web resources for changes and notify users by email
# Copyright (C) 2013  The Open Knowledge Foundation
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from db.mongo import MongoCollection
import datetime

class Users(MongoCollection):
    """
    The users collection stores all users, information about them, and the
    sites they follow and should get notified about
    """

    __collection__ = 'users'

    def __init__(self, settings, *args, **kwargs):
        """
        Overwrite the MongoCollection __init__ to store settings in an instance
        variable, self.settings
        """

        self.settings = settings
        super(Users,self).__init__(settings, *args, **kwargs)

    def all(self, filters={}):
        """
        Get all users (they can be filtered via a parameter value
        """

        # Get the user list and if none are found return an empty list
        users = list(self.collection.find(filters))

        # If no users are found we return an empty list
        if users is None:
            return []

        # Rename _id key to email and return users
        for user in users:
            user['email'] = user.pop('username')

        return users

    def countries(self):
        """
        Get all countries registered to users. This is for example used to 
        filter what countries the OBI score should be loaded for.

        Output is a list of country names
        """

        # We use the aggregation pipeline to group by all of the countries
        pipeline = [{'$match':{'country':{'$exists':True, '$ne':None}}},
                    {'$group': {'_id':'$country'}}]
        # We return a list of country names. In the user db they're stored
        # as 'IS - Iceland' so we need to split them and grab the latter part
        return set([u['_id'].split(' - ')[1] for u in self.aggregate(pipeline)])
        

    def remindees(self):
        """
        Get users from the database who's sites fall within the grace period
        and return them in a list with email addresses, names, preferred 
        language, and the site titles they watch.

        Output is a list of dictionaries for each user found and the sites that
        that fall are in the grace period.
        """

        # Get grace period. We compute it back in time since we want to
        # find all pages which should be getting reminder emails (they get
        # reminders every week during the grace period)
        today = datetime.datetime.combine(datetime.date.today(),
                                          datetime.time(0))

        # We only grab pages for non-muted users and within the grace period
        # Information we need are email, name, and language
        pipeline = [{'$match':{'mute':{'$ne':True}}},
                    {'$unwind': '$sites'}, 
                    {'$match': {'sites.search_dates.start': {'$lte': today},
                                'sites.search_dates.end': {'$gte':today}}},
                    {'$group': {'_id': 
                                {'email': '$username','name':'$name',
                                 'locale':'$locale'}, 
                                'sites': {'$addToSet': 
                                          {'title':'$sites.title', 
                                           'date':'$sites.search_dates.start'
                                           }}}
                    }]
        
        # Aggregate the results and return a list of the users
        return [{'email':user['_id']['email'],
                 'name':user['_id']['name'],
                 'locale':user['_id']['locale'],
                 'sites':user['sites']} for user in self.aggregate(pipeline)]

    def normal(self):
        """
        Get all normal users, a normal user is a user who is not an admin and
        has not been muted by an administrator.
        """
        # This is just a simple filter on top of the all function
        return self.all(filters={'admin':False, 'mute':{'$ne':True}})

    def urls(self):
        """
        Get the user urls from the database as a list of strings (urls).
        """

        # We use the aggregation framework to get all of the sites urls
        # We only grab for non-muted users where there is a url
        pipeline = [{'$match':{'mute':{'$ne':True}}},
                    {'$unwind': '$sites'},
                    {'$match': {'sites.url':{'$ne':None}}},
                    {'$group': {'_id':'all', 
                                'sites': {'$addToSet':'$sites.url'}}
                     }]

        # Since we aggregate everything into all we only need the first result
        # and the sites list in that result
        results = self.aggregate(pipeline)
        return results[0]['sites'] if len(results) else []

    def have_url(self, url):
        """
        Get all users that are following a site identified with the given url.
        These users must also be non-muted since we don't care about muted
        users.
        """
        # Simple wrapper around a call to all
        return self.all({'sites.url':site, 'mute':{'$ne':True}})

    def touch(self, site):
        """
        No this is not named so because we're trying to be funny about the
        python convention of 'self'. This is a reference to the *nix command
        touch. This updates the last_changed variable for the site for all 
        users.
        """

        # We set multi to true since there might be many users for the same
        # site (but we don't update users that have been muted)
        self.collection.update({'sites.url': site, 'mute':{'$ne':True}}, 
                               {'$set': {'sites.$.last_change':\
                                             datetime.datetime.now()}}, 
                               multi=True)


class Checksums(MongoCollection):
    """
    The checksums collection stores the checksums for all linked urls for
    sites that are stored (and the site itself).
    """

    __collection__ = 'checksums'

    def all(self):
        """
        Get all checksums of all sites in the collection
        """

        # We use the aggregation framework to get all checksums for the sites
        pipeline = [{'$group': {'_id': '$site',
                                'checksums': {'$push': '$checksum'}}
                     }]

        # Create a dictionary where the site url is the key with a set of
        # all checksums for that site as the value
        return {r['_id']:set(r['checksums']) for r in self.aggregate(pipeline)}

    def update(self, site, url, checksum):
        """
        Update a checksum as the value for a site, url combination in the
        database collection.
        """

        # The reason we use findAndModify is that it returns the old
        # document. This means that if we want to check if this is a
        # new insertion the result will be None and not None if it's an
        # update to an existing document
        return self.collection.find_and_modify(query={'site':site, 'url': url},
                                               update={'checksum': checksum},
                                               upsert=True)

    def remove(self, site, checksums):
        """
        Remove any url for a given site that has a checksum which is in
        the provided checksum list. 
        """
        self.collection.remove({'site':site, 'checksum': {'$in': checksums}})

class Countries(MongoCollection):
    """
    The countries collection stores information about countries, such as the
    OBI score
    """

    __collection__ = 'countries'

    def update_scores(self, code, country, scores):
        """
        Upsert the database scores for a given country. We only update if
        the scores have changed.
        """
        # Scores must be sorted by year
        sorted_scores = sorted(scores, key=lambda x: x['year'])
        # Update the scores
        self.collection.update({'country':country, 'code': code},
                               {'$set': {'obi_scores':sorted_scores}},
                               upsert=True)
