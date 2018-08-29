from weasel import script

# ad_migration has the script for starting lwsmd and enabling AD ports in firewall
class AdMigration:
    @staticmethod
    def getFirstBootVals():
       keyVals = {} 
       keyVals["AD"] = True
       return keyVals

#acceptancelevel normalizes the imageprofile and hostimage acceptance levels.
class AcceptanceLevelMigration:
    @staticmethod
    def getFirstBootVals():
       keyVals = {} 
       keyVals["acceptanceLevel"] = True
       return keyVals
