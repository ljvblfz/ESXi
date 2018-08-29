#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from pluginApi import GenericProfile, FixedPolicyOption, Policy, \
                      ParameterMetadata, CreateLocalizedException, \
                      CreateLocalizedMessage, log, IsString, \
                      PolicyOptComplianceChecker, \
                      TASK_LIST_RES_OK, TASK_LIST_REQ_REBOOT

from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING, COMPONENT_CONSOLE_CONFIG
from pluginApi import CreateComplianceFailureValues, POLICY_NAME, \
                      FindClassWithMatchingAttr

# Define error message keys
BASE_MSG_KEY = 'com.vmware.profile.keyboardProfile'
MODIFY_MSG_KEY = '%s.Modify' % BASE_MSG_KEY
CHANGED_MSG_KEY = '%s.ChangedKeyboard' % BASE_MSG_KEY

# Define ESXCLI constants
KEYBOARD_LAYOUT_NAMESPACES = [ 'system', 'settings', 'keyboard', 'layout' ]
KEYBOARD_LAYOUT_LIST_CMD = 'list'
KEYBOARD_LAYOUT_GET_CMD = 'get'
KEYBOARD_LAYOUT_SET_CMD = 'set'
KEYBOARD_LAYOUT_OPT = '--layout="%s"'

class KeyboardLanguageChecker(PolicyOptComplianceChecker):
   """Compliance checker that determines if the currently selected language
      in the host profile matches the setting on the system.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices,
                             profileData):
      """Checks if the current policy option matches the current keyboard
         language setting.
      """
      currentLang, _possibleLangs = profileData
      profileLang = policyOpt.__class__.language
      if currentLang != profileLang:
         complyFailure = CreateLocalizedMessage(None, CHANGED_MSG_KEY,
               {'hostKeyboard' : currentLang, 'profileKeyboard' : profileLang})

         # Find the policy option class whose 'language' is currentLang.
         hostPolicyOption = FindClassWithMatchingAttr(
            profile.policies[0].possibleOptions, 'language', currentLang)
         assert hostPolicyOption is not None
         comparisonValues = CreateComplianceFailureValues(
            'KeyboardLanguagePolicy', POLICY_NAME,
            profileValue = policyOpt.__class__.__name__,
            hostValue = hostPolicyOption)
         return (False, [(complyFailure, [comparisonValues])])

      return True, []

class KeyboardLanguageOption(FixedPolicyOption):
   """Policy Option to select the keyboard language.
   """
   paramMeta = []
   # Subclasses must provide a language attribute. 
   # language = None

   # Need a compliance checker that will determine if we have the correct
   # language setting
   complianceChecker = KeyboardLanguageChecker

class UsDefaultLanguageOption(KeyboardLanguageOption):
   """Policy Option to select the default keyboard language.
   """
   language = 'US Default'


class FrenchLanguageOption(KeyboardLanguageOption):
   """Policy Option to select French as the keyboard language.
   """
   language = 'French'


class GermanLanguageOption(KeyboardLanguageOption):
   """Policy Option to select German as the keyboard language.
   """
   language = 'German'


class JapaneseLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Japanese as the keyboard language.
   """
   language = 'Japanese'


class RussianLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Russian as the keyboard language.
   """
   language = 'Russian'


class UsDvorakLanguageOption(KeyboardLanguageOption):
   """Policy Option to select US Dvorak as the keyboard language.
   """
   language = 'US Dvorak'


class SwedishLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Swedish as the keyboard language.
   """
   language = 'Swedish'


class BrazilianLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Brazilian as the keyboard language.
   """
   language = 'Brazilian'


class IcelandicLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Icelandic as the keyboard language.
   """
   language = 'Icelandic'


class EstonianLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Estonian as the keyboard language.
   """
   language = 'Estonian'


class TurkishLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Turkish as the keyboard language.
   """
   language = 'Turkish'


class SlovenianLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Slovenian as the keyboard language.
   """
   language = 'Slovenian'


class CzechoslovakianLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Czechoslovakian as the keyboard language.
   """
   language = 'Czechoslovakian'


class LatinAmericanLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Latin American as the keyboard language.
   """
   language = 'Latin American'


class BelgianLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Belgian as the keyboard language.
   """
   language = 'Belgian'


class DanishLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Danish as the keyboard language.
   """
   language = 'Danish'


class UkrainianLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Ukrainian as the keyboard language.
   """
   language = 'Ukrainian'


class NorwegianLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Norwegian as the keyboard language.
   """
   language = 'Norwegian'


class CroatianLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Croatian as the keyboard language.
   """
   language = 'Croatian'


class FinnishLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Finnish as the keyboard language.
   """
   language = 'Finnish'


class GreekLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Greek as the keyboard language.
   """
   language = 'Greek'


class ItalianLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Italian as the keyboard language.
   """
   language = 'Italian'


class PortugueseLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Portuguese as the keyboard language.
   """
   language = 'Portuguese'


class UnitedKingdomLanguageOption(KeyboardLanguageOption):
   """Policy Option to select United Kingdom as the keyboard language.
   """
   language = 'United Kingdom'


class SpanishLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Spanish as the keyboard language.
   """
   language = 'Spanish'


class PolishLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Polish as the keyboard language.
   """
   language = 'Polish'


class SwissFrenchLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Swiss French as the keyboard language.
   """
   language = 'Swiss French'


class SwissGermanLanguageOption(KeyboardLanguageOption):
   """Policy Option to select Swiss German as the keyboard language.
   """
   language = 'Swiss German'


class KeyboardLanguagePolicy(Policy):
   """Define a policy for the Kernel Module profile containing the name.
   """
   possibleOptions = [ UsDefaultLanguageOption,
                       UsDvorakLanguageOption,
                       FrenchLanguageOption,
                       GermanLanguageOption,
                       JapaneseLanguageOption,
                       RussianLanguageOption,
                       SwedishLanguageOption,
                       IcelandicLanguageOption,
                       EstonianLanguageOption,
                       TurkishLanguageOption,
                       SlovenianLanguageOption,
                       CzechoslovakianLanguageOption,
                       LatinAmericanLanguageOption,
                       BrazilianLanguageOption,
                       BelgianLanguageOption,
                       DanishLanguageOption,
                       UkrainianLanguageOption,
                       NorwegianLanguageOption,
                       CroatianLanguageOption,
                       FinnishLanguageOption,
                       GreekLanguageOption,
                       ItalianLanguageOption,
                       PortugueseLanguageOption,
                       UnitedKingdomLanguageOption,
                       SpanishLanguageOption,
                       PolishLanguageOption,
                       SwissFrenchLanguageOption,
                       SwissGermanLanguageOption ]


class KeyboardProfile(GenericProfile):
   """A Host Profile that manages Kernel Modules on ESX hosts. This is a
      non-singleton/array profile that returns one instance per kernel module
      on the system.
   """
   #
   # Define required class attributes
   #
   policies = [ KeyboardLanguagePolicy ]
   singleton = True

   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_CONSOLE_CONFIG

   # Having the policy opt compliance checker is sufficient
   #complianceChecker = 


   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves the current language.
      """
      # Get the available list of languages
      listArgs = KEYBOARD_LAYOUT_NAMESPACES[:]
      listArgs.append(KEYBOARD_LAYOUT_LIST_CMD)
      status, output = hostServices.ExecuteEsxcli(*listArgs)
      if status != 0:
         raise Exception('Failed to list keyboard languages: ' + output)
      possibleLanguages = set([lang['Layout'] for lang in output])

      # Get the current keyboard layout
      getArgs = KEYBOARD_LAYOUT_NAMESPACES[:]
      getArgs.append(KEYBOARD_LAYOUT_GET_CMD)
      status, output = hostServices.ExecuteEsxcli(*getArgs)
      if status != 0:
         raise Exception('Failed to get current keyboard language: ' + output)
      keyboardLanguage = output

      return keyboardLanguage, possibleLanguages


   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      """Returns a profile containing the currently selected language for
         the keyboard.
      """
      currentLanguage, _possibleLangs = profileData
      policyOpt = None
      for optType in KeyboardLanguagePolicy.possibleOptions:
         if optType.language == currentLanguage:
            policyOpt = optType([])

      assert policyOpt is not None, 'Unexpected language: ' + currentLanguage
      policy = KeyboardLanguagePolicy(True, policyOpt)
      profile = cls([policy])

      return profile


   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      """Determines if the keyboard setting needs to be modified.
      """
      assert len(profileInstances) == 1
      currentLanguage, possibleLangs = profileData
      languagePolicy = profileInstances[0].KeyboardLanguagePolicy
      profileLanguage = languagePolicy.policyOption.__class__.language
      if currentLanguage != profileLanguage:
         msgKey = MODIFY_MSG_KEY + profileLanguage.replace(' ', '')
         taskMsg = CreateLocalizedMessage(None, msgKey)
         assert profileLanguage in possibleLangs
         taskList.addTask(taskMsg, profileLanguage)
      return TASK_LIST_RES_OK

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Sets the current keyboard setting.
      """
      assert len(taskList) == 1 and IsString(taskList[0])
      newLang = taskList[0]

      esxcliArgs = KEYBOARD_LAYOUT_NAMESPACES[:]
      esxcliArgs.append(KEYBOARD_LAYOUT_SET_CMD)
      esxcliArgs.append(KEYBOARD_LAYOUT_OPT % newLang)
      status, result = hostServices.ExecuteEsxcli(*esxcliArgs)
      if status != 0:
         log.error('Failed to set keyboard layout to %s: %s' % (newLang, result))
      else:
         log.info('Set keyboard layout to ' + newLang)
