
import numpy as np

from seisflows.tools import unix
from seisflows.tools.arraytools import loadnpy, savenpy
from seisflows.tools.codetools import loadtxt, savetxt, join
from seisflows.tools.configtools import ParameterObject
from seisflows.optimize import lib

PAR = ParameterObject('parameters')
PATH = ParameterObject('paths')



class default(object):
    """ Nonlinear optimization base class.

     Available nonlinear optimization aglorithms include gradient descent,
     nonlinear conjugatue gradient, and a quasi-Newton method 
     (limited-memory BFGS).

     Available line search algorithms include a backtracking line search based
     on quadratic interpolation and a bracketing and interpolation procedure
     (abbreviated as 'Backtrack' and 'BracketMinimum' respectively.)

     To reduce memory overhead, input vectors are read from the directory
     cls.path rather than passed from a calling routine. At the start of each
     search direction computation, the current model and gradient are read from
     'm_new' and 'g_new'; the resulting search direction is written to 'p_new'.
     As the optimization procedure progresses, other information is stored in
     the cls.path directory.
    """

    def __init__(cls):

        # check scratch paths
        if 'SUBMIT' not in PATH:
            raise Exception

        if 'SUBMIT' not in PATH:
            raise Exception

        if 'OPTIMIZE' not in PATH:
            setattr(PATH,'OPTIMIZE',join(PATH.GLOBAL,'optimize'))


        # check optimization parameters
        if 'BEGIN' not in PAR:
            raise Exception

        if 'END' not in PAR:
            raise Exception

        if 'SCHEME' not in PAR:
            setattr(PAR,'SCHEME','QuasiNewton')

        if 'NLCGMAX' not in PAR:
            setattr(PAR,'NLCGMAX',10)

        if 'NLCGTHRESH' not in PAR:
            setattr(PAR,'NLCGTHRESH',0.5)

        if 'LBFGSMAX' not in PAR:
            setattr(PAR,'LBFGSMAX',6)


        # check line search parameters
        if 'SRCHTYPE' not in PAR:
            setattr(PAR,'SRCHTYPE','Backtrack')

        if 'SRCHMAX' not in PAR:
            setattr(PAR,'SRCHMAX',10)

        if 'STEPLEN' not in PAR:
            setattr(PAR,'STEPLEN',0.05)

        if 'STEPMAX' not in PAR:
            setattr(PAR,'STEPMAX',0.)


    def setup(cls):
        cls.iter = PAR.BEGIN-1

        cls.path = PATH.OPTIMIZE
        unix.mkdir(cls.path)

        cls.output = PATH.SUBMIT+'/'+'output.optim'

        # prepare algorithm machinery
        if PAR.SCHEME in ['ConjugateGradient']:
            cls.NLCG = lib.NLCG(cls.path,PAR.NLCGTHRESH,PAR.NLCGMAX)

        elif PAR.SCHEME in ['QuasiNewton']:
            cls.LBFGS = lib.LBFGS(cls.path,PAR.LBFGSMAX,PAR.BEGIN)


    def compute_direction(cls):
        """ Computes model update direction from function and gradient values
        """
        cls.iter += 1

        unix.cd(cls.path)
        m_new = loadnpy('m_new')
        f_new = loadtxt('f_new')
        g_new = loadnpy('g_new')

        if PAR.SCHEME=='GradientDescent':
            p_new = -g_new

        elif PAR.SCHEME=='ConjugateGradient':
            # compute NLCG udpate
            p_new = cls.NLCG.compute()

        elif PAR.SCHEME=='QuasiNewton':
            # compute L-BFGS update
            if cls.iter==1:
                p_new = -g_new
            else:
                cls.LBFGS.update()
                p_new = -cls.LBFGS.solve()

        # save results
        unix.cd(cls.path)
        savenpy('p_new',p_new)
        savetxt('s_new',np.dot(g_new,p_new))



    ### line search methods

    def initialize_search(cls):
        """ Determines initial step length for line search
        """
        unix.cd(cls.path)
        if cls.iter==1:
            s_new = loadtxt('s_new')
            f_new = loadtxt('f_new')
            g = loadnpy('g_new')
        else:
            s_old = loadtxt('s_old')
            s_new = loadtxt('s_new')
            f_old = loadtxt('f_old')
            f_new = loadtxt('f_new')
            alpha = loadtxt('alpha')

        m = loadnpy('m_new')
        p = loadnpy('p_new')

        # reset search history
        cls.search_history = [[0.,f_new]]
        cls.isdone = 0
        cls.isbest = 0
        cls.isbrak = 0

        # compute length ratio
        mask = np.invert(m==0)
        len_m = np.median(m[mask])
        len_d = max(abs(p[mask]))
        cls.step_ratio = float(len_m/len_d)

        if cls.iter==1:
            if PAR.STEPLEN != 0.:
                alpha = PAR.STEPLEN*cls.step_ratio
            else:
                alpha = 1./np.sum(np.abs(g))
        elif PAR.SCHEME in ['GradientDescent','ConjugateGradient']:
            alpha = 2.*alpha*s_old/s_new
        else:
            alpha = 1.

        # ad hoc scaling
        if 0:
            alpha *= 1

        # limit maximum step length
        if PAR.STEPMAX > 0.:
            if alpha/cls.step_ratio > PAR.STEPMAX:
                alpha = PAR.STEPMAX*cls.step_ratio

        # write trial model
        savenpy('m_try',m+p*alpha)
        savetxt('alpha',alpha)

        with open(cls.output,'a') as file:
            file.write('Iteration '+str(cls.iter)+'\n')
            file.write(' %9.4e %9.4e\n'%(0.,f_new))


    def search_status(cls):
        """ Determines status of line search
        """
        unix.cd(cls.path)
        f0 = loadtxt('f_new')
        g0 = loadtxt('s_new')
        x_ = loadtxt('alpha')
        f_ = loadtxt('f_try')

        cls.search_history += [[x_,f_]]

        x = cls.step_lens()
        f = cls.func_vals()

        # is current step length the best so far?
        vals = cls.func_vals(sort=False)
        if np.all(vals[-1] < vals[:-1]):
            cls.isbest = 1

        # are stopping criteria satisfied?
        if PAR.SRCHTYPE=='Backtrack':
            if any(f[1:] < f[0]):
                cls.isdone = 1

        elif PAR.SRCHTYPE=='BracketMinimum':
            if cls.isbrak:
                cls.isbest = 1
                cls.isdone = 1
            elif any(f[1:] < f[0]) and (f[-2] < f[-1]):
                cls.isbrak = 1

        elif PAR.SRCHTYPE=='FixedStep':
            if any(f[1:] < f[0]) and (f[-2] < f[-1]):
                cls.isdone = 1

        with open(cls.output,'a') as file:
            file.write(' %9.4e %9.4e\n'%(x_,f_))
            if cls.isdone: file.write('\n')

        return cls.isdone, cls.isbest


    def compute_step(cls):
        """ Computes next trial step length
        """
        unix.cd(cls.path)
        m0 = loadnpy('m_new')
        p = loadnpy('p_new')
        f0 = loadtxt('f_new')
        g0 = loadtxt('s_new')

        x = cls.step_lens()
        f = cls.func_vals()

        GOLDENRATIO = 1.618034

        # compute trial step length
        if PAR.SRCHTYPE=='Backtrack':
            alpha = lib.backtrack2(f0,g0,x[1],f[1],b1=0.1,b2=0.5)

        elif PAR.SRCHTYPE=='BracketMinimum':
            if any(f[1:] < f[0]) and (f[-2] < f[-1]):
                alpha = lib.polyfit2(x,f)
            elif any(f[1:] < f[0]):
                alpha = loadtxt('alpha')*GOLDENRATIO
            else:
                alpha = loadtxt('alpha')*GOLDENRATIO**-1

        elif PAR.SRCHTYPE=='FixedStep':
            alpha = cls.step_ratio*(step+1)*PAR.STEPLEN

        # write trial model
        savetxt('alpha',alpha)
        savenpy('m_try',m0+p*alpha)


    def finalize_search(cls):
        """ Cleans working directory and writes updated model
        """
        unix.cd(cls.path)
        m0 = loadnpy('m_new')
        p = loadnpy('p_new')

        x = cls.step_lens()
        f = cls.func_vals()

        # clean working directory
        unix.rm('alpha')
        unix.rm('m_try')
        unix.rm('f_try')

        if cls.iter > 1:
            unix.rm('m_old')
            unix.rm('f_old')
            unix.rm('g_old')
            unix.rm('p_old')
            unix.rm('s_old')

        unix.mv('m_new','m_old')
        unix.mv('f_new','f_old')
        unix.mv('g_new','g_old')
        unix.mv('p_new','p_old')
        unix.mv('s_new','s_old')

        # write updated model
        alpha = x[f.argmin()]
        savetxt('alpha',alpha)
        savenpy('m_new',m0+p*alpha)
        savetxt('f_new',f.min())



    ### line search utilities

    def step_lens(cls,sort=True):
        x,f = zip(*cls.search_history)
        x = np.array(x)
        f = np.array(f)
        f_sorted = f[abs(x).argsort()]
        x_sorted = x[abs(x).argsort()]
        if sort:
            return x_sorted
        else:
            return x

    def func_vals(cls,sort=True):
        x,f = zip(*cls.search_history)
        x = np.array(x)
        f = np.array(f)
        f_sorted = f[abs(x).argsort()]
        x_sorted = x[abs(x).argsort()]
        if sort:
            return f_sorted
        else:
            return f
