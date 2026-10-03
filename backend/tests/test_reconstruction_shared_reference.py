import unittest
import numpy as np
from reconstruction_shared_v2 import initialization_reference


def fixture():
    local={}
    for name,width,role in [('wide',90.,'train'),('supported',80.,'train'),('dev',100.,'development')]:
        marks=np.zeros((468,2));marks[10]=[0.,-50.];marks[152]=[0.,50.]
        marks[234]=[-width*.5,0.];marks[454]=[width*.5,0.]
        local[name]={'marks':marks,'role':role,'F':np.eye(4)}
    return {'train':['wide','supported'],'local':local,'worlds':{n:np.eye(4) for n in local}}


class SharedReferenceContracts(unittest.TestCase):
    def test_existing_supported_second_choice_is_preserved(self):
        data=fixture();data['reference']='supported'
        self.assertEqual(initialization_reference(data),'supported')
        self.assertEqual(data['reference'],'supported')

    def test_missing_invalid_development_or_local_only_reference_is_rejected(self):
        for choice in ['missing','dev',None]:
            data=fixture();data['reference']=choice
            with self.assertRaises(ValueError):initialization_reference(data)
        data=fixture();data['reference']='supported';del data['worlds']['supported']
        with self.assertRaises(ValueError):initialization_reference(data)

    def test_no_reference_retains_original_max_width_training_choice(self):
        data=fixture();self.assertEqual(initialization_reference(data),'wide')
        self.assertNotIn('reference',data)


if __name__=='__main__':unittest.main()
